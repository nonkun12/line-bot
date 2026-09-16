"""Provider-neutral stock quote contracts and safe normalization helpers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class StockQuote:
    """Normalized market quote independent of any data vendor."""

    ticker: str
    price: float
    currency: str = ""
    previous_close: float | None = None
    change: float | None = None
    change_pct: float | None = None
    observed_at: datetime | None = None

    @property
    def display_ticker(self) -> str:
        return self.ticker[:-2] if self.ticker.endswith(".T") else self.ticker


class StockQuoteProvider(Protocol):
    """Minimal injectable provider used by stock agents."""

    def get_quote(self, ticker: str) -> StockQuote | None:
        ...


def normalize_stock_ticker(value: str) -> str:
    """Normalize Japanese four-digit codes while leaving global tickers intact."""
    ticker = str(value or "").strip().upper()
    if ticker.isdigit() and len(ticker) == 4:
        return f"{ticker}.T"
    return ticker


def safe_stock_quote(provider: StockQuoteProvider, value: str) -> StockQuote | None:
    """Return a quote only when the provider returns a structurally valid quote."""
    ticker = normalize_stock_ticker(value)
    if not ticker:
        return None
    try:
        quote = provider.get_quote(ticker)
    except Exception:
        return None
    if not isinstance(quote, StockQuote):
        return None
    if normalize_stock_ticker(quote.ticker) != ticker:
        return None
    if not isinstance(quote.price, (int, float)):
        return None
    if quote.price < 0:
        return None
    return quote
