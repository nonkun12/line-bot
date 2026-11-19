from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from datetime import datetime


DEFAULT_CATEGORY = "agent_execution_log"


@dataclass
class ExecutionLogEntry:
    """
    Represents a single agent execution log entry.
    """

    category: str = DEFAULT_CATEGORY
    agent_name: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    state: Dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: Optional[BaseException] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the log entry to a serializable dictionary.
        """
        return {
            "category": self.category,
            "agent_name": self.agent_name,
            "timestamp": self.timestamp.isoformat(),
            "state": self.state,
            "result": self.result,
            "error": repr(self.error) if self.error else None,
            "metadata": self.metadata,
        }
