from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import obsidian_mac_startup as startup


def test_load_env_file_ignores_comments_and_blank_lines(tmp_path: Path):
    env_file = tmp_path / "bridge.env"
    env_file.write_text(
        '# comment\nOBSIDIAN_BRIDGE_SERVER_URL=https://example.test\n\nOBSIDIAN_VAULT_PATH="/tmp/vault"\n',
        encoding="utf-8",
    )

    assert startup._load_env_file(env_file) == {
        "OBSIDIAN_BRIDGE_SERVER_URL": "https://example.test",
        "OBSIDIAN_VAULT_PATH": "/tmp/vault",
    }


def test_startup_checker_never_claims_when_no_pending_job():
    response = MagicMock()
    response.json.return_value = {"ok": True, "pending": False}
    response.raise_for_status.return_value = None

    with patch.object(startup, "_load_env_file", return_value={
        "OBSIDIAN_BRIDGE_SERVER_URL": "https://example.test",
        "OBSIDIAN_BRIDGE_KEY": "secret",
        "OBSIDIAN_VAULT_PATH": "/tmp/vault",
    }), patch.object(startup.httpx, "get", return_value=response) as get_mock, \
         patch.object(startup, "_ask_execute") as ask_mock:
        assert startup.main() == 0

    get_mock.assert_called_once()
    ask_mock.assert_not_called()


def test_startup_checker_requires_explicit_execute():
    response = MagicMock()
    response.json.return_value = {"ok": True, "pending": True}
    response.raise_for_status.return_value = None

    with patch.object(startup, "_load_env_file", return_value={
        "OBSIDIAN_BRIDGE_SERVER_URL": "https://example.test",
        "OBSIDIAN_BRIDGE_KEY": "secret",
        "OBSIDIAN_VAULT_PATH": "/tmp/vault",
    }), patch.object(startup.httpx, "get", return_value=response), \
         patch.object(startup, "_ask_execute", return_value=False), \
         patch.object(startup.subprocess, "run") as run_mock:
        assert startup.main() == 0

    run_mock.assert_not_called()
