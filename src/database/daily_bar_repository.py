"""Repository for the market_daily_bar table."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.database.connection import get_connection

logger = logging.getLogger(__name__)

TABLE_NAME = "market_daily_bar"


@dataclass(frozen=True)
class DailyBarRow:
    symbol: str
    con_id: int | None
    security_type: str
    exchange: str
    primary_exchange: str
    currency: str
    trade_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int
    wap: Decimal | None
    bar_count: int | None
    what_to_show: str
    source: str


@dataclass(frozen=True)
class DailyBarSummary:
    symbol: str
    what_to_show: str
    min_date: date | None
    max_date: date | None
    row_count: int


def verify_table_exists() -> bool:
    """Return True if market_daily_bar exists in the database's search path."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass(%s)", (TABLE_NAME,))
            (result,) = cur.fetchone()
    return result is not None


def get_latest_trade_date(symbol: str, what_to_show: str) -> date | None:
    """Return the most recent stored trade_date for symbol/what_to_show, or None if no rows exist."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT MAX(trade_date)
                FROM market_daily_bar
                WHERE symbol = %s
                  AND what_to_show = %s
                """,
                (symbol, what_to_show),
            )
            (latest,) = cur.fetchone()
    return latest


_UPSERT_SQL = """
    INSERT INTO market_daily_bar (
        symbol, con_id, security_type, exchange, primary_exchange, currency,
        trade_date, open_price, high_price, low_price, close_price,
        volume, wap, bar_count, what_to_show, source, created_at, updated_at
    )
    VALUES (
        %(symbol)s, %(con_id)s, %(security_type)s, %(exchange)s, %(primary_exchange)s, %(currency)s,
        %(trade_date)s, %(open_price)s, %(high_price)s, %(low_price)s, %(close_price)s,
        %(volume)s, %(wap)s, %(bar_count)s, %(what_to_show)s, %(source)s, now(), now()
    )
    ON CONFLICT (symbol, trade_date, what_to_show)
    DO UPDATE SET
        con_id = EXCLUDED.con_id,
        security_type = EXCLUDED.security_type,
        exchange = EXCLUDED.exchange,
        primary_exchange = EXCLUDED.primary_exchange,
        currency = EXCLUDED.currency,
        open_price = EXCLUDED.open_price,
        high_price = EXCLUDED.high_price,
        low_price = EXCLUDED.low_price,
        close_price = EXCLUDED.close_price,
        volume = EXCLUDED.volume,
        wap = EXCLUDED.wap,
        bar_count = EXCLUDED.bar_count,
        source = EXCLUDED.source,
        updated_at = now()
"""


def upsert_daily_bars(rows: list[DailyBarRow]) -> int:
    """Batch upsert daily bars. Returns the number of rows processed (inserted or updated)."""
    if not rows:
        return 0

    params = [
        {
            "symbol": row.symbol,
            "con_id": row.con_id,
            "security_type": row.security_type,
            "exchange": row.exchange,
            "primary_exchange": row.primary_exchange,
            "currency": row.currency,
            "trade_date": row.trade_date,
            "open_price": row.open_price,
            "high_price": row.high_price,
            "low_price": row.low_price,
            "close_price": row.close_price,
            "volume": row.volume,
            "wap": row.wap,
            "bar_count": row.bar_count,
            "what_to_show": row.what_to_show,
            "source": row.source,
        }
        for row in rows
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(_UPSERT_SQL, params)

    logger.info("Upserted %d rows into %s", len(rows), TABLE_NAME)
    return len(rows)


def get_daily_bar_summary(symbol: str, what_to_show: str) -> DailyBarSummary:
    """Return row count and stored date range for symbol/what_to_show."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT MIN(trade_date), MAX(trade_date), COUNT(*)
                FROM market_daily_bar
                WHERE symbol = %s
                  AND what_to_show = %s
                """,
                (symbol, what_to_show),
            )
            min_date, max_date, row_count = cur.fetchone()

    return DailyBarSummary(
        symbol=symbol,
        what_to_show=what_to_show,
        min_date=min_date,
        max_date=max_date,
        row_count=row_count,
    )
