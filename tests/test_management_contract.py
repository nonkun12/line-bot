import pytest

from core.management_contract import (
    ManagementDecision,
    ManagementRequest,
    Specialist,
    default_specialist_boundaries,
)


def test_management_request_requires_user_and_message() -> None:
    with pytest.raises(ValueError, match="user_id"):
        ManagementRequest("", "hello")
    with pytest.raises(ValueError, match="message"):
        ManagementRequest("u1", "")


def test_management_decision_validates_confidence() -> None:
    assert ManagementDecision(Specialist.GENERAL, "fallback", 0.5).specialist is Specialist.GENERAL
    with pytest.raises(ValueError, match="confidence"):
        ManagementDecision(Specialist.GENERAL, "fallback", 1.1)


def test_default_boundaries_keep_specialists_explicit() -> None:
    boundaries = default_specialist_boundaries()
    names = tuple(item.specialist for item in boundaries)
    assert names == (
        Specialist.GENERAL,
        Specialist.VOICE,
        Specialist.ENGLISH,
        Specialist.NEWS,
        Specialist.STOCKS,
    )
    voice = boundaries[1]
    assert voice.allowed_channels == ("voice",)
    assert "text_to_speech" in voice.capabilities
