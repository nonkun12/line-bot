"""
Tests for dev_notes factory pattern and environment variable control.

Verifies that ENABLE_EXECUTION_LOGGING environment variable
correctly switches between NoOpLogAdapter and McpNotesLogAdapter.
"""

import os
import pytest

from dev_notes.factory import get_default_adapter
from dev_notes.base import NoOpLogAdapter
from dev_notes.mcp_notes_adapter import McpNotesLogAdapter


class TestDevNotesFactory:
    """Test factory adapter selection."""

    def test_default_adapter_no_env_var(self, monkeypatch):
        """
        When ENABLE_EXECUTION_LOGGING is not set,
        get_default_adapter() returns NoOpLogAdapter.
        """
        monkeypatch.delenv("ENABLE_EXECUTION_LOGGING", raising=False)

        adapter = get_default_adapter()

        assert isinstance(adapter, NoOpLogAdapter)
        assert not isinstance(adapter, McpNotesLogAdapter)

    def test_adapter_with_enable_true(self, monkeypatch):
        """
        When ENABLE_EXECUTION_LOGGING=true,
        get_default_adapter() returns McpNotesLogAdapter.
        """
        monkeypatch.setenv("ENABLE_EXECUTION_LOGGING", "true")

        adapter = get_default_adapter()

        assert isinstance(adapter, McpNotesLogAdapter)

    def test_adapter_with_enable_1(self, monkeypatch):
        """
        When ENABLE_EXECUTION_LOGGING=1,
        get_default_adapter() returns McpNotesLogAdapter.
        """
        monkeypatch.setenv("ENABLE_EXECUTION_LOGGING", "1")

        adapter = get_default_adapter()

        assert isinstance(adapter, McpNotesLogAdapter)

    def test_adapter_with_enable_yes(self, monkeypatch):
        """
        When ENABLE_EXECUTION_LOGGING=yes,
        get_default_adapter() returns McpNotesLogAdapter.
        """
        monkeypatch.setenv("ENABLE_EXECUTION_LOGGING", "yes")

        adapter = get_default_adapter()

        assert isinstance(adapter, McpNotesLogAdapter)

    def test_adapter_with_enable_on(self, monkeypatch):
        """
        When ENABLE_EXECUTION_LOGGING=on,
        get_default_adapter() returns McpNotesLogAdapter.
        """
        monkeypatch.setenv("ENABLE_EXECUTION_LOGGING", "on")

        adapter = get_default_adapter()

        assert isinstance(adapter, McpNotesLogAdapter)

    def test_adapter_with_disable_false(self, monkeypatch):
        """
        When ENABLE_EXECUTION_LOGGING=false,
        get_default_adapter() returns NoOpLogAdapter (safe-by-default).
        """
        monkeypatch.setenv("ENABLE_EXECUTION_LOGGING", "false")

        adapter = get_default_adapter()

        assert isinstance(adapter, NoOpLogAdapter)
        assert not isinstance(adapter, McpNotesLogAdapter)

    def test_adapter_with_disable_0(self, monkeypatch):
        """
        When ENABLE_EXECUTION_LOGGING=0,
        get_default_adapter() returns NoOpLogAdapter (safe-by-default).
        """
        monkeypatch.setenv("ENABLE_EXECUTION_LOGGING", "0")

        adapter = get_default_adapter()

        assert isinstance(adapter, NoOpLogAdapter)
        assert not isinstance(adapter, McpNotesLogAdapter)

    def test_adapter_with_empty_string(self, monkeypatch):
        """
        When ENABLE_EXECUTION_LOGGING is set to empty string,
        get_default_adapter() returns NoOpLogAdapter.
        """
        monkeypatch.setenv("ENABLE_EXECUTION_LOGGING", "")

        adapter = get_default_adapter()

        assert isinstance(adapter, NoOpLogAdapter)
        assert not isinstance(adapter, McpNotesLogAdapter)

    def test_adapter_with_invalid_value(self, monkeypatch):
        """
        When ENABLE_EXECUTION_LOGGING is set to an invalid value,
        get_default_adapter() returns NoOpLogAdapter (safe-by-default).
        """
        monkeypatch.setenv("ENABLE_EXECUTION_LOGGING", "invalid")

        adapter = get_default_adapter()

        assert isinstance(adapter, NoOpLogAdapter)
        assert not isinstance(adapter, McpNotesLogAdapter)

    def test_adapter_case_insensitive(self, monkeypatch):
        """
        ENABLE_EXECUTION_LOGGING value parsing is case-insensitive.
        """
        monkeypatch.setenv("ENABLE_EXECUTION_LOGGING", "TRUE")

        adapter = get_default_adapter()

        assert isinstance(adapter, McpNotesLogAdapter)

        monkeypatch.setenv("ENABLE_EXECUTION_LOGGING", "Yes")

        adapter = get_default_adapter()

        assert isinstance(adapter, McpNotesLogAdapter)

    def test_adapter_whitespace_trimmed(self, monkeypatch):
        """
        ENABLE_EXECUTION_LOGGING value is trimmed of leading/trailing whitespace.
        """
        monkeypatch.setenv("ENABLE_EXECUTION_LOGGING", "  true  ")

        adapter = get_default_adapter()

        assert isinstance(adapter, McpNotesLogAdapter)
