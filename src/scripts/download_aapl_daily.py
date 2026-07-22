"""Download AAPL daily historical bars from IBKR TWS and store them in PostgreSQL.

Workflow: load config -> verify PostgreSQL -> verify table -> query latest
stored date -> choose initial/incremental duration -> connect to TWS ->
resolve contract -> request daily bars -> validate/normalize -> exclude a
potentially incomplete current-day bar -> upsert -> print summary.
"""
from __future__ import annotations

import logging
import re
import sys
from datetime import date, datetime
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
_INCREMENTAL_DURATION_PATTERN = re.compile(r"^(\d+)\s+D$")
_INCREMENTAL_DURATION_LOOKBACK_BUFFER_DAYS = 5

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


def _parse_incremental_duration_days(duration: str) -> int:
    match = _INCREMENTAL_DURATION_PATTERN.match(duration.strip())
    if match is None:
        raise ConfigError(
            "AAPL_INCREMENTAL_DURATION must be in the format '<positive integer> D', "
            f"got: {duration!r}"
        )
    days = int(match.group(1))
    if days <= 0:
        raise ConfigError(
            "AAPL_INCREMENTAL_DURATION must be a positive integer number of days, "
            f"got: {duration!r}"
        )
    return days


def _choose_duration(
    latest_date: date | None, now_ny_date: date, settings: Settings
) -> tuple[str, bool, int | None]:
    is_initial = latest_date is None
    if is_initial:
        return settings.aapl.initial_duration, is_initial, None

    minimum_incremental_days = _parse_incremental_duration_days(settings.aapl.incremental_duration)
    days_since_latest = (now_ny_date - latest_date).days
    requested_days = max(minimum_incremental_days, days_since_latest + _INCREMENTAL_DURATION_LOOKBACK_BUFFER_DAYS)
    return f"{requested_days} D", is_initial, days_since_latest


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
    _configure_logging()# print where the error happen

    try:
        settings = get_settings()
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        return 1

    logger.info(  # 输出 INFO 级别日志
        "PostgreSQL target: host=%s port=%s db=%s user=%s",  # 日志格式模板（避免敏感信息泄漏，不打印密码）
        settings.postgres.host,  # 数据库的主机名/IP
        settings.postgres.port,  # 数据库服务端口（默认 5432）
        settings.postgres.database,  # 目标数据库名称
        settings.postgres.user,  # 连接使用的用户名
    )

    try:
        _verify_postgres()# 尝试执行数据库连接验证函数
    except psycopg.OperationalError as exc:
        logger.error("Could not connect to PostgreSQL: %s", exc)
        return 1
    logger.info("PostgreSQL connection OK")

    try:
        if not repo.verify_table_exists():# Check if the table already exist
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
        latest_date = repo.get_latest_trade_date(SYMBOL, WHAT_TO_SHOW)# find the latest date through symbol and what_to_show
    except psycopg.Error as exc:
        logger.error("Failed to query latest trade date: %s", exc)
        return 1

    now_ny_date = datetime.now(_NEW_YORK_TZ).date()

    try:
        duration, is_initial, days_since_latest = _choose_duration(latest_date, now_ny_date, settings)
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        return 1

    logger.info(
        "Mode=%s latest_stored_date=%s days_since_latest=%s request_duration=%s",
        "initial" if is_initial else "incremental",
        latest_date,
        days_since_latest if days_since_latest is not None else "N/A",
        duration,
    )

    client = IbkrHistoricalDataClient(# 实例化自定义的 IBKR 历史数据客户端类
        host=settings.ibkr.host,
        port=settings.ibkr.port,
        client_id=settings.ibkr.client_id,
    )

    bars: list[HistoricalBar] = []#used to store K线
    con_id: int | None = None#contract ID

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
            req_id=client.next_request_id(),#生成一个唯一的请求ID
            timeout_seconds=settings.ibkr.connection_timeout_seconds,
        )
        con_id = details.contract.conId#从 IBKR 返回的完整合约详情中提取出唯一标识符 conId
        logger.info("Resolved AAPL contract: con_id=%s", con_id)

        bars = client.request_daily_bars(#最终数据列表
            contract,
            req_id=client.next_request_id(),
            duration=duration,#请求时间跨度
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

    now_ny = datetime.now(_NEW_YORK_TZ)#过滤掉当天未收盘，数据还不完整的日K线
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
        processed = repo.upsert_daily_bars(valid_rows)#将清洗/校验后的 K 线数据安全地写入 PostgreSQL 数据库，并进行异常捕捉与日志记录。
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
