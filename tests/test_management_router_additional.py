from core.management_contract import ManagementRequest, Specialist
from core.management_router import route


def test_market_keyword_routes_to_market():
    decision = route(
        ManagementRequest(
            user_id="test-user",
            message="ドル円とNYダウを確認して",
            channel="test",
            metadata={"run_id": "router-test-1"},
        )
    )
    assert decision.specialist is Specialist.MARKET
    assert decision.metadata["routing"] == "deterministic"


def test_stock_keyword_routes_to_stocks():
    decision = route(
        ManagementRequest(
            user_id="test-user",
            message="トヨタの株価を確認して",
            channel="test",
            metadata={},
        )
    )
    assert decision.specialist is Specialist.STOCKS


def test_unmatched_request_stays_general():
    decision = route(
        ManagementRequest(
            user_id="test-user",
            message="今日は開発状況を整理して",
            channel="test",
            metadata={},
        )
    )
    assert decision.specialist is Specialist.GENERAL
    assert decision.confidence == 0.60


def test_metadata_is_copied_not_reused():
    metadata = {"source": "trial"}
    decision = route(
        ManagementRequest(
            user_id="test-user",
            message="ニュースを調べて",
            channel="test",
            metadata=metadata,
        )
    )
    assert decision.metadata["request_metadata"] == metadata
    assert decision.metadata["request_metadata"] is not metadata
