from __future__ import annotations

import pytest

from core.management_contract import Specialist
from core.specialist_registry import SpecialistRegistration, SpecialistRegistry


def test_registry_registers_and_returns_specialist() -> None:
    handler = lambda *_: "ok"
    registration = SpecialistRegistration(
        specialist=Specialist.ENGLISH,
        handler=handler,
        capabilities=("english_learning",),
    )
    registry = SpecialistRegistry()

    registry.register(registration)

    assert registry.get(Specialist.ENGLISH) is registration
    assert registry.capabilities(Specialist.ENGLISH) == ("english_learning",)
    assert registry.specialists() == (Specialist.ENGLISH,)


def test_registry_can_initialize_from_registrations() -> None:
    english = SpecialistRegistration(Specialist.ENGLISH, lambda *_: "english")
    stocks = SpecialistRegistration(Specialist.STOCKS, lambda *_: "stocks")

    registry = SpecialistRegistry((english, stocks))

    assert registry.get(Specialist.ENGLISH) is english
    assert registry.get(Specialist.STOCKS) is stocks
    assert registry.specialists() == (Specialist.ENGLISH, Specialist.STOCKS)


def test_registry_rejects_duplicate_specialist() -> None:
    registry = SpecialistRegistry()
    registration = SpecialistRegistration(Specialist.NEWS, lambda *_: None)
    registry.register(registration)

    with pytest.raises(ValueError, match="specialist already registered"):
        registry.register(registration)


def test_registration_rejects_non_specialist() -> None:
    with pytest.raises(TypeError, match="specialist must be a Specialist"):
        SpecialistRegistration("news", lambda *_: None)  # type: ignore[arg-type]


def test_registration_rejects_non_callable_handler() -> None:
    with pytest.raises(TypeError, match="handler must be callable"):
        SpecialistRegistration(Specialist.NEWS, object())  # type: ignore[arg-type]


def test_registration_rejects_blank_capability() -> None:
    with pytest.raises(ValueError, match="capabilities must not contain blank values"):
        SpecialistRegistration(Specialist.NEWS, lambda *_: None, ("", "news_retrieval"))


def test_registry_missing_specialist_is_safe() -> None:
    registry = SpecialistRegistry()

    assert registry.get(Specialist.STOCKS) is None
    assert registry.capabilities(Specialist.STOCKS) == ()
