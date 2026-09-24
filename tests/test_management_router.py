from core.management_contract import ManagementRequest, Specialist
from core.management_router import route


def test_routes_specialist_requests_deterministically() -> None:
    assert route(ManagementRequest("u", "株価を教えて")).specialist is Specialist.STOCKS
    assert route(ManagementRequest("u", "英語を勉強したい")).specialist is Specialist.ENGLISH
    assert route(ManagementRequest("u", "最新ニュースを教えて")).specialist is Specialist.NEWS
    assert route(ManagementRequest("u", "音声で話して")).specialist is Specialist.VOICE
    assert route(ManagementRequest("u", "求人を探して")).specialist is Specialist.JOBS
    assert route(ManagementRequest("u", "NYダウを教えて")).specialist is Specialist.MARKET
    assert route(ManagementRequest("u", "ドル円を教えて")).specialist is Specialist.MARKET
    assert route(ManagementRequest("u", "音楽を選曲して")).specialist is Specialist.MUSIC
    assert route(ManagementRequest("u", "動画の台本を作って")).specialist is Specialist.VIDEO


def test_falls_back_to_general() -> None:
    decision = route(ManagementRequest("u", "今日は何をしよう？"))
    assert decision.specialist is Specialist.GENERAL
    assert decision.metadata["routing"] == "deterministic"


def test_general_does_not_capture_specialist_request() -> None:
    decision = route(ManagementRequest("u", "Englishで会話したい"))
    assert decision.specialist is Specialist.ENGLISH
    assert decision.confidence == 0.95


def test_preserves_multi_specialist_candidates_and_priority() -> None:
    decision = route(ManagementRequest("u", "音楽を作りながら英語も勉強したい"))
    assert decision.specialist is Specialist.ENGLISH
    assert decision.metadata["matched_specialists"] == ["english", "music"]
    assert decision.metadata["routing_priority"] == 2


def test_unresolved_request_records_empty_candidates() -> None:
    decision = route(ManagementRequest("u", "今日は何をしよう？"))
    assert decision.specialist is Specialist.GENERAL
    assert decision.metadata["matched_specialists"] == []
    assert decision.metadata["routing_priority"] is None


def test_normalizes_full_width_input_and_preserves_channel_metadata() -> None:
    request = ManagementRequest(
        "u",
        "Ｅｎｇｌｉｓｈで会話したい",
        channel="slack",
        metadata={"source": "parallel-dev-test"},
    )
    decision = route(request)
    assert decision.specialist is Specialist.ENGLISH
    assert decision.metadata["channel"] == "slack"
    assert decision.metadata["request_metadata"]["source"] == "parallel-dev-test"


def test_preserves_metadata_without_channel() -> None:
    request = ManagementRequest(
        "u",
        "Englishで会話したい",
        metadata={"source": "test-source"},
    )
    decision = route(request)
    assert decision.specialist is Specialist.ENGLISH
    assert decision.metadata["request_metadata"]["source"] == "test-source"
