from agents.english_agent import build_english_responder
from core.agents import AgentRequest


def test_empty_responder_fails_closed():
    handler = build_english_responder(lambda lesson: "")
    try:
        handler(AgentRequest(user_id="U1", message="英語"))
    except ValueError as exc:
        assert str(exc) == "English responder returned empty text"
    else:
        raise AssertionError("expected empty responder to fail closed")
