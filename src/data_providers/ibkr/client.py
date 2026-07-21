"""Native IBKR TWS API client for AAPL daily historical bars."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from ibapi.client import EClient
from ibapi.common import BarData
from ibapi.contract import Contract, ContractDetails
from ibapi.wrapper import EWrapper

logger = logging.getLogger(__name__)

# Status/informational codes IBKR sends through error() that are not request
# failures (connectivity and market-data-farm notifications).
_INFORMATIONAL_ERROR_CODES = {
    1100, 1101, 1102, 1300,
    2100, 2103, 2104, 2105, 2106, 2107, 2108, 2119, 2158,
}


class IbkrConnectionError(RuntimeError):
    """Raised when the client cannot connect to TWS/IB Gateway within the timeout."""


class IbkrTimeoutError(RuntimeError):
    """Raised when a request does not complete within the configured timeout."""


class IbkrRequestError(RuntimeError):
    """Raised when IBKR reports a fatal error for a request."""


@dataclass(frozen=True)
class HistoricalBar:
    trade_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int
    wap: Decimal | None
    bar_count: int | None


def _parse_daily_date(raw: str) -> date:
    """Parse an IBKR daily bar date (formatDate=1 -> 'YYYYMMDD', optionally with a time suffix)."""
    value = raw.strip().split(" ")[0]
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise ValueError(f"Unrecognized IBKR daily bar date format: {raw!r}") from exc


def _parse_decimal(raw: object, field_name: str) -> Decimal:
    try:
        return Decimal(str(raw))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid numeric value for {field_name}: {raw!r}") from exc


def _parse_volume(raw: object) -> int:
    try:
        return int(Decimal(str(raw)))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid volume value: {raw!r}") from exc


def _parse_bar(bar: BarData) -> HistoricalBar:
    wap = None
    if bar.wap is not None:
        wap_value = _parse_decimal(bar.wap, "wap")
        if wap_value >= 0:
            wap = wap_value

    bar_count = None
    if bar.barCount is not None and int(bar.barCount) >= 0:
        bar_count = int(bar.barCount)

    return HistoricalBar(
        trade_date=_parse_daily_date(bar.date),
        open_price=_parse_decimal(bar.open, "open"),
        high_price=_parse_decimal(bar.high, "high"),
        low_price=_parse_decimal(bar.low, "low"),
        close_price=_parse_decimal(bar.close, "close"),
        volume=_parse_volume(bar.volume),
        wap=wap,
        bar_count=bar_count,
    )


class IbkrHistoricalDataClient(EWrapper, EClient):
    """Minimal synchronous wrapper around the IBKR historical-data API for a single symbol."""

    def __init__(self, host: str, port: int, client_id: int) -> None:
        EClient.__init__(self, self)
        self._host = host
        self._port = port
        self._client_id = client_id

        self._next_valid_id: int | None = None
        self._connected_event = threading.Event()
        self._run_thread: threading.Thread | None = None

        self._contract_details_req_id: int | None = None
        self._contract_details_event = threading.Event()
        self._contract_details: ContractDetails | None = None
        self._contract_details_count = 0

        self._historical_req_id: int | None = None
        self._historical_event = threading.Event()
        self._historical_bars: list[HistoricalBar] = []

        self._errors: list[tuple[int, int, str]] = []

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect_and_start(self, timeout_seconds: float) -> None:
        """Connect to TWS/IB Gateway and wait for nextValidId confirmation."""
        self.connect(self._host, self._port, self._client_id)
        self._run_thread = threading.Thread(target=self.run, daemon=True, name="ibkr-client-run")
        self._run_thread.start()

        if not self._connected_event.wait(timeout=timeout_seconds):
            raise IbkrConnectionError(
                f"Timed out waiting for IBKR connection confirmation "
                f"(host={self._host}, port={self._port}, client_id={self._client_id})"
            )

    def disconnect_clean(self) -> None:
        if self.isConnected():
            self.disconnect()

    def next_request_id(self) -> int:
        if self._next_valid_id is None:
            raise IbkrConnectionError("Cannot generate a request id before nextValidId is received")
        request_id = self._next_valid_id
        self._next_valid_id += 1
        return request_id

    # ------------------------------------------------------------------
    # Contract resolution
    # ------------------------------------------------------------------

    def resolve_contract(self, contract: Contract, req_id: int, timeout_seconds: float) -> ContractDetails:
        """Resolve a contract via reqContractDetails, raising if invalid, ambiguous, or timed out."""
        self._contract_details_req_id = req_id
        self._contract_details_event.clear()
        self._contract_details = None
        self._contract_details_count = 0

        self.reqContractDetails(req_id, contract)

        if not self._contract_details_event.wait(timeout=timeout_seconds):
            raise IbkrTimeoutError(f"Timed out resolving contract for reqId={req_id}")

        errors = self._errors_for(req_id)
        if self._contract_details_count == 0:
            raise IbkrRequestError(f"IBKR returned no contract details for reqId={req_id}: {errors}")
        if self._contract_details_count > 1:
            raise IbkrRequestError(
                f"IBKR contract is ambiguous for reqId={req_id}: "
                f"{self._contract_details_count} matches returned"
            )

        assert self._contract_details is not None
        return self._contract_details

    # ------------------------------------------------------------------
    # Historical data
    # ------------------------------------------------------------------

    def request_daily_bars(
        self,
        contract: Contract,
        req_id: int,
        duration: str,
        timeout_seconds: float,
    ) -> list[HistoricalBar]:
        """Request daily ADJUSTED_LAST bars and block until historicalDataEnd or timeout."""
        self._historical_req_id = req_id
        self._historical_event.clear()
        self._historical_bars = []

        self.reqHistoricalData(
            reqId=req_id,
            contract=contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting="1 day",
            whatToShow="ADJUSTED_LAST",
            useRTH=1,
            formatDate=1,
            keepUpToDate=False,
            chartOptions=[],
        )

        if not self._historical_event.wait(timeout=timeout_seconds):
            raise IbkrTimeoutError(f"Timed out waiting for historical data (reqId={req_id})")

        errors = self._errors_for(req_id)
        if errors and not self._historical_bars:
            raise IbkrRequestError(f"IBKR historical data request failed (reqId={req_id}): {errors}")

        return list(self._historical_bars)

    def _errors_for(self, req_id: int) -> list[tuple[int, int, str]]:
        return [entry for entry in self._errors if entry[0] == req_id]

    # ------------------------------------------------------------------
    # EWrapper callbacks
    # ------------------------------------------------------------------

    def nextValidId(self, orderId: int) -> None:
        self._next_valid_id = orderId
        self._connected_event.set()

    def contractDetails(self, reqId: int, contractDetails: ContractDetails) -> None:
        if reqId != self._contract_details_req_id:
            return
        self._contract_details = contractDetails
        self._contract_details_count += 1

    def contractDetailsEnd(self, reqId: int) -> None:
        if reqId == self._contract_details_req_id:
            self._contract_details_event.set()

    def historicalData(self, reqId: int, bar: BarData) -> None:
        if reqId != self._historical_req_id:
            return
        try:
            self._historical_bars.append(_parse_bar(bar))
        except ValueError as exc:
            logger.error("Skipping unparsable historical bar for reqId=%d: %s", reqId, exc)

    def historicalDataEnd(self, reqId: int, start: str, end: str) -> None:
        if reqId == self._historical_req_id:
            self._historical_event.set()

    def error(
        self,
        req_id,
        error_time,
        error_code,
        error_string,
        advanced_order_reject_json="",
    ):
        # Matches the ibapi 10.48 EWrapper.error signature, which inserts
        # error_time before error_code.
        if error_code in _INFORMATIONAL_ERROR_CODES:
            logger.info("IBKR status [reqId=%s code=%s]: %s", req_id, error_code, error_string)
            return

        logger.error("IBKR error [reqId=%s code=%s]: %s", req_id, error_code, error_string)
        self._errors.append((req_id, error_code, error_string))

        if req_id == self._contract_details_req_id:
            self._contract_details_event.set()
        if req_id == self._historical_req_id:
            self._historical_event.set()

    def connectionClosed(self) -> None:
        logger.warning("IBKR connection closed")
