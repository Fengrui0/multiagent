"""Contract construction helpers for IBKR requests."""
from __future__ import annotations

from ibapi.contract import Contract


def build_aapl_contract() -> Contract:
    """Return the base AAPL STK contract used for market-data requests."""
    contract = Contract()
    contract.symbol = "AAPL"
    contract.secType = "STK"
    contract.exchange = "SMART"
    contract.primaryExchange = "ISLAND"
    contract.currency = "USD"
    return contract
