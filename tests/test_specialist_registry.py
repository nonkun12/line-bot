import pytest

from core.management_contract import Specialist
from core.specialist_registry import SpecialistRegistration, SpecialistRegistry


def test_registry_registers_and_returns_specialist() -> None:
    handler = object()
    registry = SpecialistRegistry(
        (SpecialistRegistration(Specialist.ENGLISH, handler, ("english_learning",)),)
    )

    item = registry.get(Specialist.ENGLISH)
    assert item is not None
    assert item.handler is handler
    assert item.capabilities == ("english_learning",)
    assert registry.specialists() == (Specialist.ENGLISH,)


def test_registry_rejects_duplicate_specialist() -> None:
    registration = SpecialistRegistration(Specialist.NEWS, lambda: None)
    registry = SpecialistRegistry((registration,))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(registration)


def test_registry_missing_specialist_returns_none() -> None:
    registry = SpecialistRegistry()
    assert registry.get(Specialist.STOCKS) is None
