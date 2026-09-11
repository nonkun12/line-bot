import pytest

from graph.supervisor import classify_intent, supervisor_node


@pytest.mark.parametrize(
    "message",
    ["単語", "クイズ", "文法", "会話", "復習", "review"],
)
def test_supervisor_routes_english_follow_up_modes(message: str) -> None:
    assert classify_intent(message, user_id="test-user") == "english_learning"

    state = supervisor_node(
        {
            "user_id": "test-user",
            "raw_message": message,
            "channel": "line",
            "metadata": {},
        }
    )

    assert state["intent"] == "english_learning"
    assert state["next_agent"] == "english_learning"
