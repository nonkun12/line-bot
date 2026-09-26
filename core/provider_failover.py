"""Bounded provider failover state for the LINE Bot normal-response path."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass


@dataclass
class _ProviderState:
    unavailable_until: float = 0.0


class ProviderFailover:
    """Keep a small in-process circuit state for Gemini and Groq.

    The primary provider is retried automatically after its cooldown expires.
    A failed provider is never retried more than once for the same request.
    """

    PROVIDERS = ("gemini", "groq")

    def __init__(self, *, cooldown_seconds: float | None = None) -> None:
        if cooldown_seconds is None:
            try:
                cooldown_seconds = float(os.getenv("AI_PROVIDER_COOLDOWN_SECONDS", "60"))
            except ValueError:
                cooldown_seconds = 60.0
        self._cooldown_seconds = max(1.0, min(float(cooldown_seconds), 900.0))
        self._lock = threading.Lock()
        self._state = {provider: _ProviderState() for provider in self.PROVIDERS}

    def available(self, provider: str) -> bool:
        if provider not in self.PROVIDERS:
            return False
        with self._lock:
            return time.monotonic() >= self._state[provider].unavailable_until

    def mark_failure(self, provider: str) -> None:
        if provider not in self.PROVIDERS:
            return
        with self._lock:
            self._state[provider].unavailable_until = time.monotonic() + self._cooldown_seconds

    def mark_success(self, provider: str) -> None:
        if provider not in self.PROVIDERS:
            return
        with self._lock:
            self._state[provider].unavailable_until = 0.0

    def ordered(self, primary: str = "gemini") -> tuple[str, ...]:
        """Return currently available providers in priority order."""
        primary = primary if primary in self.PROVIDERS else "gemini"
        secondary = "groq" if primary == "gemini" else "gemini"
        return tuple(
            provider
            for provider in (primary, secondary)
            if self.available(provider)
        )

    def both_unavailable(self, primary: str = "gemini") -> bool:
        return not self.ordered(primary)


provider_failover = ProviderFailover()


__all__ = ["ProviderFailover", "provider_failover"]
