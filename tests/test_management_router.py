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


def test_english_takes_priority_for_music_composition_and_english_learning() -> None:
    decision = route(ManagementRequest("u", "音楽を作曲しながら英語を学習したい"))
    assert decision.specialist is Specialist.ENGLISH
