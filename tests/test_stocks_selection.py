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
    assert all(-5 <= item.score <= 5 for item in ranked)


def test_missing_history_is_neutral():
    indicators = analyze_prices([100, 101, 99])

    assert indicators.signal == "neutral"
    assert indicators.sma20 is None
    assert indicators.sma50 is None


from agents.stocks.node import StocksAgent
from core.agents import AgentRequest


def test_volatility20_requires_21_closes():
    assert analyze_prices([100 + i for i in range(20)]).volatility20 is None
    assert analyze_prices([100 + i for i in range(21)]).volatility20 is not None


def test_analysis_response_contains_real_newlines():
    quote = {"price": 150.0, "currency": "JPY"}
    response = StocksAgent._analysis_response("TEST", "1234.T", quote, [100 + i for i in range(60)])

    assert "\n" in response.text
    assert "\\n" not in response.text
    assert "RSI14:" in response.text
    assert "MACD:" in response.text


def test_analysis_request_triggers_for_indicators():
    assert StocksAgent._is_analysis_request("7203のRSIとMACDを分析して")
    assert StocksAgent._is_analysis_request("銘柄選定して")
    assert not StocksAgent._is_analysis_request("7203の株価")


def test_analysis_history_failure_fails_closed(monkeypatch):
    agent = StocksAgent()
    monkeypatch.setattr(agent, "_fetch_quote", lambda ticker: {
        "ticker": "7203", "price": 3000.0, "currency": "JPY",
        "change": 0.0, "change_pct": 0.0, "market_state": "CLOSED",
        "market_time_jst": None,
    })
    def fail_history(ticker):
        raise RuntimeError("history unavailable")
    monkeypatch.setattr(agent, "_fetch_history", fail_history)

    response = agent.handle(AgentRequest(user_id="u1", message="トヨタのRSIを分析して"))

    assert response.metadata["status"] == "degraded"
    assert "不足データを推測せず" in response.text
    assert "売買シグナルは表示しません" in response.text
