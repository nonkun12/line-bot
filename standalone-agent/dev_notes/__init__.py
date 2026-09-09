"""
Development notes logging package.

Optional execution logging layer for AI agents.
Default behavior is disabled.
"""

from .settings import is_logging_enabled
from .factory import get_default_adapter
from .base import DevNotesLogAdapter, NoOpLogAdapter
from .mcp_notes_adapter import McpNotesLogAdapter

__all__ = [
    "is_logging_enabled",
    "get_default_adapter",
    "DevNotesLogAdapter",
    "NoOpLogAdapter",
    "McpNotesLogAdapter",
]
