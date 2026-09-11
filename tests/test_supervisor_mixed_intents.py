import pytest

from graph.supervisor import classify_intent, supervisor_node


@pytest.mark.parametrize(
    ("message", "expected_intent", "expected_agent"),
    [
        ("英語の勉強方法を教えて", "english_learning", "english_learning"),
        ("株価を見たい 銘柄 7203", "stocks", "stocks"),
        ("AI NEWSを見せて", "ai_news", "ai_news"),
        ("AIスピーカーでしゃべって", "voice", "voice"),
        # Mixed requests follow the current intent-priority order in classify_intent.
        ("株価 7203 と AI NEWS を教えて", "ai_news", "ai_news"),
        ("英語を勉強したい、株価 7203 も見たい", "stocks", "stocks"),
    ],
)
def test_supervisor_mixed_and_single_feature_routing(
    message: str,
    expected_intent: str,
    expected_agent: str,
) -> None:
    assert classify_intent(message, user_id="test-user") == expected_intent

    state = supervisor_node(
        {
            "user_id": "test-user",
            "raw_message": message,
            "channel": "line",
            "metadata": {},
        }
    )
    assert state["intent"] == expected_intent
    assert state["next_agent"] == expected_agent
