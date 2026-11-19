from __future__ import annotations

from .settings import is_logging_enabled
from .base import DevNotesLogAdapter, NoOpLogAdapter
from .mcp_notes_adapter import McpNotesLogAdapter


def get_default_adapter() -> DevNotesLogAdapter:
    """
    Return the default logging adapter.

    Disabled:
        NoOpLogAdapter

    Enabled:
        McpNotesLogAdapter
    """

    if not is_logging_enabled():
        return NoOpLogAdapter()

    return McpNotesLogAdapter()
