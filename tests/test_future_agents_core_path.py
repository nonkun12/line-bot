from __future__ import annotations

import pytest

from agents.english.node import agent as english_agent
from agents.news.node import AINewsAgent, agent as news_agent
from agents.stocks.node import StocksAgent, agent as stocks_agent
from agents.voice.node import agent as voice_agent
from core import AgentRegistry, build_core_graph
from graph.supervisor import supervisor_node


@pytest.mark.parametrize(
    ("message", "expected_intent", "expected_agent"),
    [
        ("英語を勉強したい", "english_learning", "english_learning"),
        ("AI NEWSを見せて", "ai_news", "ai_news"),
        ("株価を見たい 銘柄 7203", "stocks", "stocks"),
        ("AIスピーカーでしゃべって", "voice", "voice"),
    ],
)
def test_future_agents_traverse_supervisor_to_dynamic_core_graph(
    message: str,
    expected_intent: str,
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

    state = {
        "user_id": "test-user",
        "raw_message": message,
        "channel": "line",
        "metadata": {},
    }
    supervised = supervisor_node(state)

    assert supervised["intent"] == expected_intent
    assert supervised["next_agent"] == expected_agent

    registry = AgentRegistry([english_agent, news_agent, stocks_agent, voice_agent])
    graph = build_core_graph(registry)
    result = graph.invoke(supervised)

    assert result["route"] is not None
    assert expected_agent in result["agent_results"]
    assert result["final_reply"]
    assert result["error"] is None
