"""Provider-neutral stock quote and technical-analysis contracts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from typing import Iterable, Protocol


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


@dataclass(frozen=True)
class StockHistoryPoint:
    """One normalized daily market observation."""

    observed_at: datetime
    close: float
    volume: int | None = None


@dataclass(frozen=True)
class StockAnalysis:
    """Descriptive technical indicators computed only from observed history."""

    ticker: str
    latest_close: float
    data_points: int
    return_20d_pct: float | None
    sma_20: float | None
    sma_50: float | None
    rsi_14: float | None
    volatility_20_annualized_pct: float | None
    high_20: float | None
    low_20: float | None
    latest_volume: int | None
    average_volume_20: float | None
    volume_ratio_20: float | None


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


def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return round(sum(values[-window:]) / window, 4)


def _rsi(values: list[float], window: int = 14) -> float | None:
    if len(values) <= window:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values[-window - 1 :], values[-window:]):
        delta = current - previous
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    average_gain = sum(gains) / window
    average_loss = sum(losses) / window
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    rs = average_gain / average_loss
    return round(100 - (100 / (1 + rs)), 4)


def _annualized_volatility_pct(values: list[float], window: int = 20) -> float | None:
    if len(values) <= window:
        return None
    returns = [
        (current / previous) - 1
        for previous, current in zip(values[-window - 1 :], values[-window:])
        if previous > 0 and current > 0
    ]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    return round(sqrt(variance) * sqrt(252) * 100, 4)


def analyze_history(
    ticker: str,
    history: Iterable[StockHistoryPoint],
) -> StockAnalysis | None:
    """Compute deterministic descriptive indicators from chronological history."""
    points = tuple(sorted(history, key=lambda item: item.observed_at))
    closes = [float(point.close) for point in points if isinstance(point.close, (int, float)) and point.close > 0]
    if not closes:
        return None

    return_20 = None
    if len(closes) >= 21 and closes[-21] > 0:
        return_20 = round((closes[-1] / closes[-21] - 1) * 100, 4)

    recent = closes[-20:] if len(closes) >= 20 else closes
    return StockAnalysis(
        ticker=normalize_stock_ticker(ticker),
        latest_close=closes[-1],
        data_points=len(closes),
        return_20d_pct=return_20,
        sma_20=_sma(closes, 20),
        sma_50=_sma(closes, 50),
        rsi_14=_rsi(closes),
        volatility_20_annualized_pct=_annualized_volatility_pct(closes),
        high_20=round(max(recent), 4),
        low_20=round(min(recent), 4),
        latest_volume=points[-1].volume,
        average_volume_20=(
            round(sum(point.volume for point in points[-20:] if point.volume is not None) /
                  sum(1 for point in points[-20:] if point.volume is not None), 2)
            if any(point.volume is not None for point in points[-20:])
            else None
        ),
        volume_ratio_20=(
            round(
                points[-1].volume /
                (sum(point.volume for point in points[-20:] if point.volume is not None) /
                 sum(1 for point in points[-20:] if point.volume is not None)),
                4,
            )
            if points[-1].volume is not None and any(point.volume is not None for point in points[-20:])
            else None
        ),
    )
