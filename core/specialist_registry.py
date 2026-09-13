"""Provider-neutral registry for management AI specialist handlers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from .management_contract import Specialist


SpecialistHandler = Callable[..., object]


@dataclass(frozen=True)
class SpecialistRegistration:
    specialist: Specialist
    handler: SpecialistHandler
    capabilities: tuple[str, ...] = ()
    metadata: Mapping[str, object] | None = None


class SpecialistRegistry:
    """Own the specialist-to-handler mapping without selecting providers."""

    def __init__(self, registrations: tuple[SpecialistRegistration, ...] = ()) -> None:
        self._registrations: dict[Specialist, SpecialistRegistration] = {}
        for registration in registrations:
            self.register(registration)

    def register(self, registration: SpecialistRegistration) -> None:
        if registration.specialist in self._registrations:
            raise ValueError(f"specialist already registered: {registration.specialist.value}")
        self._registrations[registration.specialist] = registration

    def get(self, specialist: Specialist) -> SpecialistRegistration | None:
        return self._registrations.get(specialist)

    def specialists(self) -> tuple[Specialist, ...]:
        return tuple(self._registrations)

    def capabilities(self, specialist: Specialist) -> tuple[str, ...]:
        registration = self.get(specialist)
        return registration.capabilities if registration is not None else ()
