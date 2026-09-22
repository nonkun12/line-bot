from agents.stocks.selection import analyze_prices, rank_stock_candidates


def test_analyze_prices_returns_bounded_technical_indicators():
    prices = [100 + i for i in range(60)]
    indicators = analyze_prices(prices)

    assert indicators.sma20 == sum(prices[-20:]) / 20
    assert indicators.sma50 == sum(prices[-50:]) / 50
    assert indicators.rsi14 == 100.0
    assert indicators.macd is not None
    assert indicators.macd_signal is not None
    assert indicators.volatility20 is not None
    assert indicators.bollinger_mid20 == sum(prices[-20:]) / 20
    assert indicators.bollinger_upper20 is not None
    assert indicators.bollinger_lower20 is not None
    assert indicators.trend == "bullish"
    assert indicators.signal == "bullish"


def test_rank_stock_candidates_is_deterministic_and_bounded():
    prices = {
        "7203": [100 + i for i in range(60)],
        "6758": [200 - i for i in range(60)],
        "8306": [100 + ((i % 2) * 0.5) for i in range(60)],
    }
    ranked = rank_stock_candidates(list(prices.items()), limit=2)

    assert len(ranked) == 2
    assert ranked[0].ticker == "7203"
    assert ranked[0].signal == "bullish"
    assert all(item.score in {-2, -1, 0, 1, 2, 3, 4} for item in ranked)


def test_missing_history_is_neutral():
    indicators = analyze_prices([100, 101, 99])

    assert indicators.signal == "neutral"
    assert indicators.sma20 is None
    assert indicators.sma50 is None
