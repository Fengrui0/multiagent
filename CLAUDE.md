# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Status

Source code has been added implementing the first market-data ingestion feature: downloading AAPL daily historical bars from the IBKR TWS API and storing them in PostgreSQL.

### Architecture

- `src/config/settings.py` - loads and caches configuration from a root-level `.env` file via `get_settings()`.
- `src/database/connection.py` - Psycopg 3 connection context manager; commits on success, rolls back on failure.
- `src/database/daily_bar_repository.py` - all SQL for the `market_daily_bar` table: latest trade date, batch upsert, summary, table existence check.
- `src/data_providers/ibkr/client.py` - native `EWrapper`/`EClient` historical-data client; the socket event loop runs in one daemon thread.
- `src/data_providers/ibkr/contracts.py` - contract builders (currently AAPL STK only).
- `src/scripts/download_aapl_daily.py` - the runnable end-to-end workflow script.
- `sql/001_create_market_daily_bar.sql` - schema migration, safe to re-run.

Only one symbol (AAPL), one provider (IBKR), and one database (PostgreSQL) are implemented. No concurrent historical-data downloads, streaming data, order placement, or backtesting exist yet.

This code has been written and syntax-checked but has not yet been verified end-to-end against a live TWS connection in this session.

### Commands

```bash
pip install -r requirements.txt

set -a
source .env
set +a

PGPASSWORD="$POSTGRES_PASSWORD" psql \
  -h "$POSTGRES_HOST" \
  -p "$POSTGRES_PORT" \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  -f sql/001_create_market_daily_bar.sql

python src/scripts/download_aapl_daily.py
```

No test framework or linter is configured yet.

## Project Goal

This project is a quantitative trading platform built from scratch.

The long-term goal is to develop a professional platform for quantitative research, backtesting, paper trading, and live trading.

---

## General Rules

- Read the relevant existing code before making changes.
- Make the smallest necessary modification.
- Only modify files, functions, and modules directly related to the current task. Do not refactor unrelated code.
- Before modifying a function, understand its existing implementation and preserve unaffected behavior unless explicitly instructed otherwise.
- Do not delete files unless explicitly requested.
- Do not generate additional project documentation unless explicitly requested.
- Do not generate test files unless explicitly requested.
- Keep this `CLAUDE.md` updated when build commands, dependencies, or architecture change.

---

## Coding Standards

- Use Python as the primary programming language.
- Write clear, maintainable, and modular code.
- Follow Clean Code principles.
- Keep functions focused on a single responsibility.
- Use type hints whenever practical.
- Handle expected errors explicitly.
- Do not add generic fallback logic, silent exception handling, or unnecessarily broad exception catches.
- Do not use emojis in source code, comments, logs, or documentation.

---

## Quantitative Trading Rules

- Never introduce look-ahead bias or use future information in research or backtests.
- Account for commissions and slippage unless explicitly disabled or not applicable.
- Preserve reproducibility in data processing, research, and backtesting.
- Keep strategy logic independent from broker-specific APIs and implementations.
- Keep research, backtesting, paper trading, and live trading as independent modules.

---

## Communication

- Explain decisions and results to the user in Chinese.
- Keep source code, identifiers, comments, docstrings, and technical terminology in English.
- Provide an implementation plan before large architectural changes.
- Identify the root cause, or clearly state the most likely cause, before proposing error fixes.
- Distinguish confirmed facts from assumptions.
- Ask for clarification when ambiguity could materially affect behavior, architecture, data integrity, or financial correctness.

---

## Dependencies

- Do not introduce new dependencies unless necessary.
- Explain why a new dependency is required before adding it.
- Do not upgrade existing dependencies unless explicitly requested.

---

## Git

- Never commit or push without explicit permission.
- Never rewrite or modify Git history unless explicitly requested.
- Check Git status before making large changes.