from __future__ import annotations

from agents.stocks.node import StocksAgent
from core.agents import AgentRequest


def test_stocks_agent_extracts_natural_ticker(monkeypatch) -> None:
    captured: list[str] = []

    def fake_quote(cls, ticker: str):
        captured.append(ticker)
        return {
            "ticker": cls._display_ticker(ticker),
            "price": 100.0,
            "previous_close": 99.0,
            "change": 1.0,
            "change_pct": 1.0101,
            "currency": "USD",
            "market_time": 0,
        }

    monkeypatch.setattr(StocksAgent, "_fetch_quote", classmethod(fake_quote))

    response = StocksAgent().handle(
        AgentRequest(user_id="test-user", message="AAPLの株価を教えて", channel="line")
    )

    assert captured == ["AAPL"]
    assert "AAPL" in response.text


def test_stocks_agent_extracts_natural_japanese_code(monkeypatch) -> None:
    captured: list[str] = []

    def fake_quote(cls, ticker: str):
        captured.append(ticker)
        return {
            "ticker": cls._display_ticker(ticker),
            "price": 3000.0,
            "previous_close": 2990.0,
            "change": 10.0,
            "change_pct": 0.3344,
            "currency": "JPY",
            "market_time": 0,
        }

    monkeypatch.setattr(StocksAgent, "_fetch_quote", classmethod(fake_quote))

    response = StocksAgent().handle(
        AgentRequest(user_id="test-user", message="7203の株価", channel="line")
    )

    assert captured == ["7203.T"]
    assert "7203" in response.text
