"""Application configuration loaded from a root-level .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values

_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _load_env() -> dict[str, str]:
    """Merge the .env file with the process environment, which takes precedence."""
    values: dict[str, str] = {
        key: value for key, value in dotenv_values(_ENV_PATH).items() if value is not None
    }
    values.update(os.environ)
    return values


def _require(env: dict[str, str], key: str) -> str:
    value = env.get(key)
    if value is None or value == "":
        raise ConfigError(f"Missing required environment variable: {key}")
    return value


def _get_str(env: dict[str, str], key: str, default: str) -> str:
    value = env.get(key)
    if value is None or value == "":
        return default
    return value


def _get_int(env: dict[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"Environment variable {key} must be an integer, got: {raw!r}") from exc


@dataclass(frozen=True)
class PostgresSettings:
    host: str
    port: int
    database: str
    user: str
    password: str

    def __repr__(self) -> str:
        return (
            f"PostgresSettings(host={self.host!r}, port={self.port}, "
            f"database={self.database!r}, user={self.user!r}, password='***')"
        )


@dataclass(frozen=True)
class IbkrSettings:
    host: str
    port: int
    client_id: int
    connection_timeout_seconds: int
    historical_timeout_seconds: int


@dataclass(frozen=True)
class AaplDownloadSettings:
    initial_duration: str
    incremental_duration: str


@dataclass(frozen=True)
class Settings:
    postgres: PostgresSettings
    ibkr: IbkrSettings
    aapl: AaplDownloadSettings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache application settings from the environment / .env file."""
    env = _load_env()

    postgres = PostgresSettings(
        host=_get_str(env, "POSTGRES_HOST", "localhost"),
        port=_get_int(env, "POSTGRES_PORT", 5432),
        database=_require(env, "POSTGRES_DB"),
        user=_require(env, "POSTGRES_USER"),
        password=_require(env, "POSTGRES_PASSWORD"),
    )

    ibkr = IbkrSettings(
        host=_get_str(env, "IBKR_HOST", "127.0.0.1"),
        port=_get_int(env, "IBKR_PORT", 7496),
        client_id=_get_int(env, "IBKR_CLIENT_ID", 1),
        connection_timeout_seconds=_get_int(env, "IBKR_CONNECTION_TIMEOUT_SECONDS", 10),
        historical_timeout_seconds=_get_int(env, "IBKR_HISTORICAL_TIMEOUT_SECONDS", 60),
    )

    aapl = AaplDownloadSettings(
        initial_duration=_get_str(env, "AAPL_INITIAL_DURATION", "5 Y"),
        incremental_duration=_get_str(env, "AAPL_INCREMENTAL_DURATION", "10 D"),
    )

    return Settings(postgres=postgres, ibkr=ibkr, aapl=aapl)
