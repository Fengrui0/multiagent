# multiagent

## Market data ingestion: AAPL daily bars (IBKR -> PostgreSQL)

Setup:

1. `pip install -r requirements.txt`
2. Install the official `ibapi` package from the IBKR TWS API download (not on PyPI): https://interactivebrokers.github.io/
3. `cp .env.example .env` and fill in your PostgreSQL and IBKR settings.
4. Apply the migration (see CLAUDE.md's Commands section for the full `source .env` + `psql` invocation using `POSTGRES_HOST`/`POSTGRES_PORT`/`POSTGRES_USER`/`POSTGRES_DB`).
5. Start TWS or IB Gateway, enable the API, and run: `python -m src.scripts.download_aapl_daily`.