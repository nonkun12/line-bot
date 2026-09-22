"""Bounded technical analysis and stock-candidate screening helpers.

The calculations are deterministic and operate only on supplied market data.
They do not place orders, fetch external data, or make personalized
investment recommendations.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Sequence


@dataclass(frozen=True)
class TechnicalIndicators:
    price: float | None
    sma20: float | None
    sma50: float | None
    rsi14: float | None
    macd: float | None
    macd_signal: float | None
    volatility20: float | None
    bollinger_mid20: float | None
    bollinger_upper20: float | None
    bollinger_lower20: float | None
    trend: str
    signal: str
    signal_score: int


def analyze_prices(prices: Sequence[float]) -> TechnicalIndicators:
    values = [float(v) for v in prices if _valid_number(v)]
    if not values:
        return TechnicalIndicators(None, None, None, None, None, None, None, None, None, None, "unknown", "neutral", 0)

    price = values[-1]
    sma20 = _sma(values, 20)
    sma50 = _sma(values, 50)
    rsi14 = _rsi(values, 14)
    ema12 = _ema(values, 12)
    ema26 = _ema(values, 26)
    macd = ema12 - ema26 if ema12 is not None and ema26 is not None else None
    macd_series = _macd_series(values, 12, 26)
    macd_signal = _ema(macd_series, 9) if macd_series else None
    volatility20 = _annualized_volatility(values[-21:]) if len(values) >= 3 else None
    bollinger_mid20, bollinger_upper20, bollinger_lower20 = _bollinger_bands(values, 20, 2.0)

    score = 0
    if sma20 is not None:
        score += 1 if price > sma20 else -1
    if sma50 is not None:
        score += 1 if price > sma50 else -1
    if rsi14 is not None:
        if rsi14 < 30:
            score += 1
        elif rsi14 > 70:
            score -= 1
    if macd is not None and macd_signal is not None:
        score += 1 if macd > macd_signal else -1
    if bollinger_upper20 is not None and bollinger_lower20 is not None:
        if price <= bollinger_lower20:
            score += 1
        elif price >= bollinger_upper20:
            score -= 1

    if sma20 is not None and sma50 is not None:
        trend = "bullish" if sma20 > sma50 else "bearish"
    elif sma20 is not None:
        trend = "bullish" if price > sma20 else "bearish"
    else:
        trend = "unknown"

    if score >= 2:
        signal = "bullish"
    elif score <= -2:
        signal = "bearish"
    else:
        signal = "neutral"

    return TechnicalIndicators(
        price=price,
        sma20=sma20,
        sma50=sma50,
        rsi14=rsi14,
        macd=macd,
        macd_signal=macd_signal,
        volatility20=volatility20,
        bollinger_mid20=bollinger_mid20,
        bollinger_upper20=bollinger_upper20,
        bollinger_lower20=bollinger_lower20,
        trend=trend,
        signal=signal,
        signal_score=score,
    )


@dataclass(frozen=True)
class StockSelectionResult:
    ticker: str
    signal: str
    score: int
    reason: str
    indicators: TechnicalIndicators


def rank_stock_candidates(
    candidates: Sequence[tuple[str, Sequence[float]]],
    *,
    limit: int = 5,
) -> tuple[StockSelectionResult, ...]:
    """Rank candidates by deterministic technical signals."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer")

    results: list[StockSelectionResult] = []
    for ticker, prices in candidates:
        indicators = analyze_prices(prices)
        if indicators.price is None:
            continue
        reason = (
            f"トレンド={indicators.trend}, "
            f"RSI14={_fmt(indicators.rsi14)}, "
            f"MACD={_fmt(indicators.macd)}, "
            f"MACDシグナル={_fmt(indicators.macd_signal)}, "
            f"SMA20={_fmt(indicators.sma20)}, "
            f"SMA50={_fmt(indicators.sma50)}, "
            f"ボリンジャー20={_fmt(indicators.bollinger_mid20)}/上限{_fmt(indicators.bollinger_upper20)}/下限{_fmt(indicators.bollinger_lower20)}"
        )
        results.append(
            StockSelectionResult(
                ticker=str(ticker),
                signal=indicators.signal,
                score=indicators.signal_score,
                reason=reason,
                indicators=indicators,
            )
        )

    results.sort(key=lambda item: (-item.score, item.ticker))
    return tuple(results[:limit])


def _valid_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _sma(values: Sequence[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _ema(values: Sequence[float], period: int) -> float | None:
    if len(values) < period:
        return None
    multiplier = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    for value in values[period:]:
        ema = (value - ema) * multiplier + ema
    return ema


def _macd_series(values: Sequence[float], fast: int, slow: int) -> list[float]:
    if len(values) < slow:
        return []
    fast_multiplier = 2.0 / (fast + 1)
    slow_multiplier = 2.0 / (slow + 1)
    fast_ema = sum(values[:fast]) / fast
    for value in values[fast:slow]:
        fast_ema = (value - fast_ema) * fast_multiplier + fast_ema
    slow_ema = sum(values[:slow]) / slow
    series = [fast_ema - slow_ema]
    for value in values[slow:]:
        fast_ema = (value - fast_ema) * fast_multiplier + fast_ema
        slow_ema = (value - slow_ema) * slow_multiplier + slow_ema
        series.append(fast_ema - slow_ema)
    return series


def _bollinger_bands(
    values: Sequence[float], period: int, deviations: float
) -> tuple[float | None, float | None, float | None]:
    if len(values) < period:
        return None, None, None
    window = values[-period:]
    mean = sum(window) / period
    variance = sum((value - mean) ** 2 for value in window) / period
    standard_deviation = sqrt(variance)
    return mean, mean + deviations * standard_deviation, mean - deviations * standard_deviation




def _rsi(values: Sequence[float], period: int) -> float | None:
    if len(values) <= period:
        return None
    gains = []
    losses = []
    for previous, current in zip(values[:-1], values[1:]):
        delta = current - previous
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _annualized_volatility(values: Sequence[float]) -> float | None:
    if len(values) < 3:
        return None
    returns = [
        (current / previous) - 1.0
        for previous, current in zip(values[:-1], values[1:])
        if previous != 0
    ]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    return sqrt(variance) * sqrt(252) * 100.0


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


__all__ = ["StockSelectionResult", "TechnicalIndicators", "analyze_prices", "rank_stock_candidates"]
