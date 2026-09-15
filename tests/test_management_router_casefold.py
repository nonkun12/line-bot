from core.management_contract import ManagementRequest, Specialist
from core.management_router import route


def test_router_normalizes_whitespace_and_case_for_keywords() -> None:
    assert route(ManagementRequest("u", "  STOCKS の 株価  ")).specialist is Specialist.STOCKS
    assert route(ManagementRequest("u", "  EnGlIsHで会話したい  ")).specialist is Specialist.ENGLISH
    assert route(ManagementRequest("u", "  NEWS を見せて  ")).specialist is Specialist.NEWS


def test_router_preserves_channel_and_metadata_on_specialist_match() -> None:
    decision = route(
        ManagementRequest(
            "u",
            "音声で話して",
            channel="line",
            metadata={"request_id": "self-improvement"},
        )
    )
    assert decision.specialist is Specialist.VOICE
    assert decision.metadata["channel"] == "line"
    assert decision.metadata["request_metadata"] == {"request_id": "self-improvement"}
