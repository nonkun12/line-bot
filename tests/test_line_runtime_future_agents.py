from __future__ import annotations

import pytest

from agents.news.node import AINewsAgent
from agents.stocks.node import StocksAgent
from core.request_path import run_core_request


@pytest.mark.parametrize(
    ("message", "expected_agent"),
    [
        ("英語を勉強したい", "english_learning"),
        ("AI NEWSを見せて", "ai_news"),
        ("株価を見たい 銘柄 7203", "stocks"),
        ("AIスピーカーでしゃべって", "voice"),
    ],
)
def test_run_core_request_reaches_future_agent(
    message: str,
    expected_agent: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if expected_agent == "ai_news":
        monkeypatch.setattr(
            AINewsAgent,
            "_fetch",
            classmethod(
                lambda cls, query: [
                    {
                        "title": "Test AI News",
                        "link": "https://example.com/ai-news",
                        "published": "09/12 05:00",
                        "source": "Test Source",
                    }
                ]
            ),
        )
    elif expected_agent == "stocks":
        monkeypatch.setattr(
            StocksAgent,
            "_fetch_quote",
            classmethod(
                lambda cls, ticker: {
                    "ticker": cls._display_ticker(ticker),
                    "price": 2500.0,
                    "previous_close": 2450.0,
                    "change": 50.0,
                    "change_pct": 2.0408,
                    "currency": "JPY",
                    "market_time": 0,
                },
            ),
        )

    result = run_core_request(
        "test-user",
        message,
        channel="line",
        metadata={"route": "line_callback"},
    )

    assert result["next_agent"] == expected_agent
    assert expected_agent in result["agent_results"]
    assert result["final_reply"]
    assert result["error"] is None
