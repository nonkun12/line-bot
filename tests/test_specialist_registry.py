from __future__ import annotations

import pytest

from core.management_contract import Specialist
from core.specialist_registry import SpecialistRegistration, SpecialistRegistry


def test_registry_registers_and_returns_specialist() -> None:
    handler = object()
    registration = SpecialistRegistration(
        specialist=Specialist.ENGLISH,
        handler=handler,  # type: ignore[arg-type]
        capabilities=("english_learning",),
    )
    registry = SpecialistRegistry()

    registry.register(registration)

    assert registry.get(Specialist.ENGLISH) is registration
    assert registry.capabilities(Specialist.ENGLISH) == ("english_learning",)
    assert registry.specialists() == (Specialist.ENGLISH,)


def test_registry_rejects_duplicate_specialist() -> None:
    registry = SpecialistRegistry()
    registration = SpecialistRegistration(Specialist.NEWS, lambda *_: None)
    registry.register(registration)

    with pytest.raises(ValueError, match="specialist already registered"):
        registry.register(registration)


def test_registry_missing_specialist_is_safe() -> None:
    registry = SpecialistRegistry()

    assert registry.get(Specialist.STOCKS) is None
    assert registry.capabilities(Specialist.STOCKS) == ()
