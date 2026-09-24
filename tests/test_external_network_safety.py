from __future__ import annotations

import pytest

from core.external_network_safety import (
    assert_no_new_external_capabilities,
    capability_fingerprint,
    new_external_capabilities,
)


def test_existing_network_call_is_allowed_when_not_introduced():
    base = "import urllib.request\n\ndef fetch(url):\n    return urllib.request.urlopen(url)\n"
    produced = base + "\n# harmless local change\n"
    assert new_external_capabilities(base, produced) == ()
    assert_no_new_external_capabilities(base, produced, "agents/example.py")


def test_new_network_import_is_blocked():
    base = "def answer():\n    return 1\n"
    produced = "import requests\n\ndef answer():\n    return requests.get('https://example.com')\n"
    with pytest.raises(RuntimeError, match="external capability"):
        assert_no_new_external_capabilities(base, produced, "agents/example.py")


def test_new_http_destination_is_blocked_even_with_existing_client():
    base = (
        "import urllib.request\n"
        "URL = 'https://api.example.com/status'\n"
        "def fetch():\n"
        "    return urllib.request.urlopen(URL)\n"
    )
    produced = base.replace(
        "https://api.example.com/status",
        "https://attacker.example.com/exfil",
    )
    new = new_external_capabilities(base, produced)
    assert "url:https://attacker.example.com/exfil" in new


def test_new_process_execution_is_blocked():
    base = "def answer():\n    return 1\n"
    produced = "import subprocess\n\nsubprocess.run(['echo', 'unsafe'])\n"
    with pytest.raises(RuntimeError, match="external capability"):
        assert_no_new_external_capabilities(base, produced, "agents/example.py")


def test_fingerprint_is_deterministic():
    source = "import socket\n"
    assert capability_fingerprint(source) == frozenset({"import:socket"})
