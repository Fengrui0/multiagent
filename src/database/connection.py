"""PostgreSQL connection management using Psycopg 3."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

from src.config.settings import PostgresSettings, get_settings


@contextmanager
def get_connection(settings: PostgresSettings | None = None) -> Iterator[psycopg.Connection]:
    """Yield a Psycopg connection, committing on success and rolling back on failure."""
    pg_settings = settings or get_settings().postgres
    conn = psycopg.connect(
        host=pg_settings.host,
        port=pg_settings.port,
        dbname=pg_settings.database,
        user=pg_settings.user,
        password=pg_settings.password,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
