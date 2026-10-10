from scripts.diagnose_obsidian_bridge_config import inspect_values


def test_diagnostic_uses_startup_file_precedence_and_reports_no_values():
    result = inspect_values(
        {
            "OBSIDIAN_BRIDGE_SERVER_URL": "https://line-bot-yvea.onrender.com/",
            "OBSIDIAN_BRIDGE_KEY": "dummy-key",
            "OBSIDIAN_VAULT_PATH": "/tmp/dummy-vault",
        },
        {
            "OBSIDIAN_BRIDGE_SERVER_URL": "http://wrong.example",
            "OBSIDIAN_BRIDGE_KEY": "other-dummy-key",
            "OBSIDIAN_VAULT_PATH": "/tmp/other-vault",
        },
    )
    assert result["url_source"] == "file"
    assert result["bridge_key_source"] == "file"
    assert result["vault_path_source"] == "file"
    assert result["url_set"] is True
    assert result["url_scheme_https"] is True
    assert result["url_hostname_present"] is True
    assert result["url_hostname_matches_expected"] is True
    assert result["url_port_parses"] is True
    assert result["bridge_validator_accepts"] is True
    assert result["diagnostic_accepts"] is True
    assert "dummy-key" not in repr(result)
    assert "line-bot-yvea" not in repr(result)


def test_diagnostic_rejects_malformed_url_without_returning_it():
    result = inspect_values(
        {
            "OBSIDIAN_BRIDGE_SERVER_URL": "https\\://line-bot-yvea.onrender.com",
            "OBSIDIAN_BRIDGE_KEY": "dummy-key",
            "OBSIDIAN_VAULT_PATH": "/tmp/dummy-vault",
        },
        {},
    )
    assert result["url_set"] is True
    assert result["bridge_validator_accepts"] is False
    assert result["bridge_validator_error"] == "invalid_server_url"
    assert "https\\://" not in repr(result)
    assert "dummy-key" not in repr(result)


def test_diagnostic_does_not_accept_an_unexpected_https_host():
    result = inspect_values(
        {
            "OBSIDIAN_BRIDGE_SERVER_URL": "https://unexpected.example",
            "OBSIDIAN_BRIDGE_KEY": "dummy-key",
            "OBSIDIAN_VAULT_PATH": "/tmp/dummy-vault",
        },
        {},
    )
    assert result["bridge_validator_accepts"] is True
    assert result["url_hostname_matches_expected"] is False
    assert result["diagnostic_accepts"] is False



def test_diagnostic_script_can_run_directly_outside_repository(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "diagnose_obsidian_bridge_config.py"
    child_env = dict(os.environ)
    child_env["HOME"] = str(tmp_path)
    child_env.pop("PYTHONPATH", None)
    for key in (
        "OBSIDIAN_BRIDGE_SERVER_URL",
        "OBSIDIAN_BRIDGE_KEY",
        "OBSIDIAN_VAULT_PATH",
    ):
        child_env.pop(key, None)

    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1  # Missing config is a safe diagnostic failure.
    assert "url_set=False" in completed.stdout
    assert "ModuleNotFoundError" not in completed.stderr
    assert "OBSIDIAN_BRIDGE_KEY" not in completed.stdout
