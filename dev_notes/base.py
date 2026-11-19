from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from .schema import DEFAULT_CATEGORY


class DevNotesLogAdapter(ABC):
    """
    Abstract base class for development notes logging adapters.

    Logging failures must never affect the caller.
    """

    @abstractmethod
    def log_execution(
        self,
        agent_name: str,
        state: Dict[str, Any],
        result: Any,
        error: Optional[BaseException] = None,
        category: str = DEFAULT_CATEGORY,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        raise NotImplementedError


class NoOpLogAdapter(DevNotesLogAdapter):
    """
    Disabled logging adapter.

    Used by default.
    """

    def log_execution(
        self,
        agent_name: str,
        state: Dict[str, Any],
        result: Any,
        error: Optional[BaseException] = None,
        category: str = DEFAULT_CATEGORY,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        return
