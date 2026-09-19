import pytest

from core.management_contract import (
    ManagementDecision,
    ManagementRequest,
    Specialist,
    default_specialist_boundaries,
    specialist_boundary,
)


def test_management_request_validation() -> None:
    with pytest.raises(ValueError):
        ManagementRequest("", "hello")
    with pytest.raises(ValueError):
        ManagementRequest("u1", "")


def test_management_decision_confidence_range() -> None:
    assert ManagementDecision(Specialist.GENERAL, "fallback", 0.5).specialist is Specialist.GENERAL
    with pytest.raises(ValueError):
        ManagementDecision(Specialist.GENERAL, "fallback", 1.1)


def test_default_boundaries_are_explicit() -> None:
    names = tuple(item.specialist for item in default_specialist_boundaries())
    assert names == (
        Specialist.GENERAL,
        Specialist.VOICE,
        Specialist.ENGLISH,
        Specialist.NEWS,
        Specialist.STOCKS,
        Specialist.MARKET,
        Specialist.JOBS,
        Specialist.MUSIC,
        Specialist.VIDEO,
    )
    assert default_specialist_boundaries()[1].allowed_channels == ("voice",)


def test_specialist_boundary_exposes_capabilities_without_mutation() -> None:
    assert specialist_boundary(Specialist.ENGLISH).capabilities == ("english_learning",)
    assert specialist_boundary(Specialist.NEWS).capabilities == ("news_retrieval",)
    assert specialist_boundary(Specialist.STOCKS).capabilities == ("stock_quotes",)
    assert specialist_boundary(Specialist.VOICE).allowed_channels == ("voice",)
