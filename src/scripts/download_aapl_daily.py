"""Download AAPL daily historical bars from IBKR TWS and store them in PostgreSQL.

Workflow: load config -> verify PostgreSQL -> verify table -> query latest
stored date -> choose initial/incremental duration -> connect to TWS ->
resolve contract -> request daily bars -> validate/normalize -> exclude a
potentially incomplete current-day bar -> upsert -> print summary.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import psycopg  # noqa: E402

from src.config.settings import ConfigError, Settings, get_settings  # noqa: E402
from src.data_providers.ibkr.client import (  # noqa: E402
    HistoricalBar,
    IbkrConnectionError,
    IbkrHistoricalDataClient,
    IbkrRequestError,
    IbkrTimeoutError,
)
from src.data_providers.ibkr.contracts import build_aapl_contract  # noqa: E402
from src.database import connection  # noqa: E402
from src.database import daily_bar_repository as repo  # noqa: E402

SYMBOL = "AAPL"
SECURITY_TYPE = "STK"
EXCHANGE = "SMART"
PRIMARY_EXCHANGE = "ISLAND"
CURRENCY = "USD"
WHAT_TO_SHOW = "ADJUSTED_LAST"
SOURCE = "IBKR"

_NEW_YORK_TZ = ZoneInfo("America/New_York")
_REGULAR_SESSION_CLOSE_HOUR = 16  # 4:00 PM America/New_York

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _verify_postgres() -> None:
    with connection.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")


def _choose_duration(latest_date, settings: Settings) -> tuple[str, bool]:
    is_initial = latest_date is None
    duration = settings.aapl.initial_duration if is_initial else settings.aapl.incremental_duration
    return duration, is_initial


def _is_potentially_incomplete_today_bar(trade_date, now_ny: datetime) -> bool:
    if trade_date != now_ny.date():
        return False
    session_close = now_ny.replace(hour=_REGULAR_SESSION_CLOSE_HOUR, minute=0, second=0, microsecond=0)
    return now_ny < session_close


def _validate_bar(bar: HistoricalBar) -> str | None:
    if bar.open_price is None or bar.high_price is None or bar.low_price is None or bar.close_price is None:
        return "missing OHLC price"
    if bar.volume is None or bar.volume < 0:
        return "volume must not be negative"
    if bar.high_price < bar.low_price:
        return "high_price is lower than low_price"
    return None


def _validate_and_convert(bars: list[HistoricalBar], con_id: int | None) -> list[repo.DailyBarRow]:
    valid_rows: list[repo.DailyBarRow] = []
    for bar in bars:
        error = _validate_bar(bar)
        if error is not None:
            logger.warning("Skipping invalid bar dated %s: %s", bar.trade_date, error)
            continue
        valid_rows.append(
            repo.DailyBarRow(
                symbol=SYMBOL,
                con_id=con_id,
                security_type=SECURITY_TYPE,
                exchange=EXCHANGE,
                primary_exchange=PRIMARY_EXCHANGE,
                currency=CURRENCY,
                trade_date=bar.trade_date,
                open_price=bar.open_price,
                high_price=bar.high_price,
                low_price=bar.low_price,
                close_price=bar.close_price,
                volume=bar.volume,
                wap=bar.wap,
                bar_count=bar.bar_count,
                what_to_show=WHAT_TO_SHOW,
                source=SOURCE,
            )
        )
    return valid_rows


def _print_summary(summary: repo.DailyBarSummary) -> None:
    logger.info(
        "Summary: symbol=%s what_to_show=%s rows=%d min_date=%s max_date=%s",
        summary.symbol,
        summary.what_to_show,
        summary.row_count,
        summary.min_date,
        summary.max_date,
    )


def main() -> int:
    _configure_logging()

    try:
        settings = get_settings()
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        return 1

    logger.info(
        "PostgreSQL target: host=%s port=%s db=%s user=%s",
        settings.postgres.host,
        settings.postgres.port,
        settings.postgres.database,
        settings.postgres.user,
    )

    try:
        _verify_postgres()
    except psycopg.OperationalError as exc:
        logger.error("Could not connect to PostgreSQL: %s", exc)
        return 1
    logger.info("PostgreSQL connection OK")

    try:
        if not repo.verify_table_exists():
            logger.error(
                "Table %s does not exist. Apply the migration: "
                "psql -f sql/001_create_market_daily_bar.sql",
                repo.TABLE_NAME,
            )
            return 1
    except psycopg.Error as exc:
        logger.error("Failed to verify table %s: %s", repo.TABLE_NAME, exc)
        return 1
    logger.info("Table %s verified", repo.TABLE_NAME)

    try:
        latest_date = repo.get_latest_trade_date(SYMBOL, WHAT_TO_SHOW)
    except psycopg.Error as exc:
        logger.error("Failed to query latest trade date: %s", exc)
        return 1

    duration, is_initial = _choose_duration(latest_date, settings)
    logger.info(
        "Mode=%s latest_stored_date=%s request_duration=%s",
        "initial" if is_initial else "incremental",
        latest_date,
        duration,
    )

    client = IbkrHistoricalDataClient(
        host=settings.ibkr.host,
        port=settings.ibkr.port,
        client_id=settings.ibkr.client_id,
    )

    bars: list[HistoricalBar] = []
    con_id: int | None = None

    try:
        client.connect_and_start(timeout_seconds=settings.ibkr.connection_timeout_seconds)
        logger.info(
            "Connected to IBKR at %s:%s (client_id=%s)",
            settings.ibkr.host,
            settings.ibkr.port,
            settings.ibkr.client_id,
        )

        contract = build_aapl_contract()

        details = client.resolve_contract(
            contract,
            req_id=client.next_request_id(),
            timeout_seconds=settings.ibkr.connection_timeout_seconds,
        )
        con_id = details.contract.conId
        logger.info("Resolved AAPL contract: con_id=%s", con_id)

        bars = client.request_daily_bars(
            contract,
            req_id=client.next_request_id(),
            duration=duration,
            timeout_seconds=settings.ibkr.historical_timeout_seconds,
        )
    except (IbkrConnectionError, IbkrTimeoutError, IbkrRequestError) as exc:
        logger.error("IBKR request failed: %s", exc)
        return 1
    finally:
        client.disconnect_clean()
        logger.info("Disconnected from IBKR")

    logger.info("Received %d bars from IBKR", len(bars))
    if not bars:
        logger.error("No historical bars were returned for %s", SYMBOL)
        return 1

    now_ny = datetime.now(_NEW_YORK_TZ)
    complete_bars = []
    excluded_count = 0
    for bar in bars:
        if _is_potentially_incomplete_today_bar(bar.trade_date, now_ny):
            excluded_count += 1
            logger.info("Excluding potentially incomplete current-day bar dated %s", bar.trade_date)
            continue
        complete_bars.append(bar)

    valid_rows = _validate_and_convert(complete_bars, con_id)
    if complete_bars and not valid_rows:
        logger.error("All returned bars failed validation")
        return 1

    logger.info(
        "Bars excluded as incomplete: %d, bars valid for upsert: %d",
        excluded_count,
        len(valid_rows),
    )

    try:
        processed = repo.upsert_daily_bars(valid_rows)
    except psycopg.Error as exc:
        logger.error("Database upsert failed: %s", exc)
        return 1
    logger.info("Rows processed by upsert: %d", processed)

    try:
        summary = repo.get_daily_bar_summary(SYMBOL, WHAT_TO_SHOW)
    except psycopg.Error as exc:
        logger.error("Failed to query summary: %s", exc)
        return 1

    _print_summary(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
