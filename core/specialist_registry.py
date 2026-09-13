"""Provider-neutral registry for management AI specialist ownership."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from .management_contract import Specialist


Handler = Callable[..., object]


@dataclass(frozen=True)
class SpecialistRegistration:
    specialist: Specialist
    handler: Handler
    capabilities: tuple[str, ...] = ()
    metadata: Mapping[str, object] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.metadata is None:
            object.__setattr__(self, "metadata", {})


class SpecialistRegistry:
    """Small explicit registry; execution policy stays outside the registry."""

    def __init__(self, registrations: tuple[SpecialistRegistration, ...] = ()) -> None:
        self._items: dict[Specialist, SpecialistRegistration] = {}
        for registration in registrations:
            self.register(registration)

    def register(self, registration: SpecialistRegistration) -> None:
        if registration.specialist in self._items:
            raise ValueError(f"specialist already registered: {registration.specialist.value}")
        self._items[registration.specialist] = registration

    def get(self, specialist: Specialist) -> SpecialistRegistration | None:
        return self._items.get(specialist)

    def specialists(self) -> tuple[Specialist, ...]:
        return tuple(self._items)

    def handlers(self) -> Mapping[Specialist, Handler]:
        return {specialist: item.handler for specialist, item in self._items.items()}
