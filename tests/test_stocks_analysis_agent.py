from agents.stocks.node import StocksAgent
from core.agents import AgentRequest
from core.stocks import StockHistoryPoint
from datetime import datetime, timedelta, timezone


def test_agent_extracts_ticker_and_returns_analysis(monkeypatch):
    points = tuple(
        StockHistoryPoint(
            observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=i),
            close=100 + i,
        )
        for i in range(60)
    )
    monkeypatch.setattr(StocksAgent, "_fetch_history", classmethod(lambda cls, ticker: ("USD", list(points))))

    response = StocksAgent().handle(
        AgentRequest("u", "AAPLを分析して", channel="slack")
    )

    assert response.metadata["feature"] == "stocks"
    assert response.metadata["mode"] == "analysis"
    assert response.metadata["ticker"] == "AAPL"
    assert "RSI14" in response.text
    assert "将来の値動きを保証する予測ではありません" in response.text


def test_analysis_without_ticker_is_explicit_about_required_input():
    response = StocksAgent().handle(AgentRequest("u", "テクニカル分析して"))
    assert response.metadata["mode"] == "analysis"
    assert "Ticker" in response.text
