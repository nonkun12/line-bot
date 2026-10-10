import json
from pathlib import Path

import httpx
from unittest.mock import MagicMock, patch

from scripts import obsidian_mac_startup as startup


def read_log_records(tmp_path):
    return [json.loads(line) for line in (tmp_path / "startup.log").read_text().splitlines()]


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


def test_startup_checker_never_claims_when_no_pending_job(tmp_path):
    response = MagicMock()
    response.json.return_value = {"ok": True, "pending": False}
    response.raise_for_status.return_value = None
    with patch.object(startup, "_load_env_file", return_value={
        "OBSIDIAN_BRIDGE_SERVER_URL": "https://example.test",
        "OBSIDIAN_BRIDGE_KEY": "dummy-key",
        "OBSIDIAN_VAULT_PATH": "/tmp/vault",
    }), patch.object(startup, "STARTUP_LOG", tmp_path / "startup.log"), \
         patch.object(startup.httpx, "get", return_value=response) as get_mock, \
         patch.object(startup, "_ask_execute") as ask_mock:
        assert startup.main() == 0
    get_mock.assert_called_once()
    ask_mock.assert_not_called()
    records = read_log_records(tmp_path)
    assert [record["event"] for record in records] == ["startup_started", "pending_none"]
    assert len({record["run_id"] for record in records}) == 1
    assert all(record["timestamp"].endswith("+00:00") for record in records)


def test_startup_rejects_non_https_url_before_network(tmp_path):
    with patch.object(startup, "_load_env_file", return_value={
        "OBSIDIAN_BRIDGE_SERVER_URL": "http://external.invalid",
        "OBSIDIAN_BRIDGE_KEY": "dummy-key",
        "OBSIDIAN_VAULT_PATH": "/tmp/vault",
    }), patch.object(startup, "STARTUP_LOG", tmp_path / "startup.log"), \
         patch.object(startup.httpx, "get") as get_mock, \
         patch.object(startup, "_notify", return_value=True):
        assert startup.main() == 1
    get_mock.assert_not_called()
    records = read_log_records(tmp_path)
    assert any(record["event"] == "configuration_invalid" for record in records)
    assert "external.invalid" not in repr(records)


def test_startup_checker_requires_explicit_execute(tmp_path):
    response = MagicMock()
    response.json.return_value = {"ok": True, "pending": True}
    response.raise_for_status.return_value = None
    with patch.object(startup, "_load_env_file", return_value={
        "OBSIDIAN_BRIDGE_SERVER_URL": "https://example.test",
        "OBSIDIAN_BRIDGE_KEY": "secret",
        "OBSIDIAN_VAULT_PATH": "/tmp/vault",
    }), patch.object(startup, "STARTUP_LOG", tmp_path / "startup.log"), \
         patch.object(startup.httpx, "get", return_value=response), \
         patch.object(startup, "_ask_execute", return_value=("later", 0)), \
         patch.object(startup.subprocess, "run") as run_mock:
        assert startup.main() == 0
    run_mock.assert_not_called()
    records = read_log_records(tmp_path)
    assert [record["event"] for record in records] == [
        "startup_started", "notification_shown", "user_deferred",
    ]


def test_execute_choice_starts_bridge_exactly_once_with_configuration(tmp_path):
    response = MagicMock()
    response.json.return_value = {"ok": True, "pending": True}
    response.raise_for_status.return_value = None
    env_values = {
        "OBSIDIAN_BRIDGE_SERVER_URL": "https://bridge-test.invalid",
        "OBSIDIAN_BRIDGE_KEY": "dummy-bridge-key",
        "OBSIDIAN_VAULT_PATH": "/tmp/dummy-vault",
    }
    with patch.object(startup, "_load_env_file", return_value=env_values), \
         patch.object(startup.httpx, "get", return_value=response), \
         patch.object(startup, "_ask_execute", return_value=("execute", 0)), \
         patch.object(startup, "_notify", return_value=True), \
         patch.object(startup, "STARTUP_LOG", tmp_path / "startup.log"), \
         patch.object(startup.subprocess, "run", side_effect=[
             MagicMock(returncode=0), MagicMock(returncode=0, stdout="", stderr=""),
         ]) as run_mock:
        assert startup.main() == 0
    bridge_calls = [call for call in run_mock.call_args_list
                    if call.args[0][0] == startup.sys.executable]
    assert len(bridge_calls) == 1
    bridge_call = bridge_calls[0]
    assert bridge_call.args[0] == [startup.sys.executable, str(startup.BRIDGE_SCRIPT)]
    assert all(bridge_call.kwargs["env"][key] == value for key, value in env_values.items())
    records = read_log_records(tmp_path)
    assert [record["event"] for record in records][-2:] == ["bridge_start", "bridge_exit"]
    assert records[-1]["exit_code"] == 0


def test_bridge_stderr_classification_is_correlated_and_sanitized(tmp_path):
    def fake_run(command, **kwargs):
        if command[0] == "/usr/bin/open":
            return MagicMock(returncode=0)
        run_id = kwargs["env"]["OBSIDIAN_BRIDGE_RUN_ID"]
        diagnostic = {
            "component": "obsidian_bridge", "run_id": run_id,
            "category": "url_validation_failed", "exception": "ValueError",
        }
        return MagicMock(
            returncode=2, stdout="SECRET JOB BODY",
            stderr=(startup.BRIDGE_DIAGNOSTIC_PREFIX + json.dumps(diagnostic)
                    + "\nraw url https://private.invalid and dummy-bridge-key"),
        )
    response = MagicMock()
    response.json.return_value = {"ok": True, "pending": True}
    response.raise_for_status.return_value = None
    with patch.object(startup, "_load_env_file", return_value={
        "OBSIDIAN_BRIDGE_SERVER_URL": "https://bridge-test.invalid",
        "OBSIDIAN_BRIDGE_KEY": "dummy-bridge-key",
        "OBSIDIAN_VAULT_PATH": "/tmp/dummy-vault",
    }), patch.object(startup, "STARTUP_LOG", tmp_path / "startup.log"), \
         patch.object(startup.httpx, "get", return_value=response), \
         patch.object(startup, "_ask_execute", return_value=("execute", 0)), \
         patch.object(startup, "_notify", return_value=True), \
         patch.object(startup.subprocess, "run", side_effect=fake_run):
        assert startup.main() == 2
    records = read_log_records(tmp_path)
    start = next(record for record in records if record["event"] == "bridge_start")
    failure = next(record for record in records if record["event"] == "bridge_diagnostic")
    assert failure["category"] == "url_validation_failed"
    assert failure["run_id"] == start["run_id"]
    assert "private.invalid" not in repr(records)
    assert "dummy-bridge-key" not in repr(records)
    assert "SECRET JOB BODY" not in repr(records)


def test_bridge_process_start_failure_logs_class_only(tmp_path):
    response = MagicMock()
    response.json.return_value = {"ok": True, "pending": True}
    response.raise_for_status.return_value = None
    with patch.object(startup, "_load_env_file", return_value={
        "OBSIDIAN_BRIDGE_SERVER_URL": "https://bridge-test.invalid",
        "OBSIDIAN_BRIDGE_KEY": "dummy-key",
        "OBSIDIAN_VAULT_PATH": "/tmp/dummy-vault",
    }), patch.object(startup, "STARTUP_LOG", tmp_path / "startup.log"), \
         patch.object(startup.httpx, "get", return_value=response), \
         patch.object(startup, "_ask_execute", return_value=("execute", 0)), \
         patch.object(startup, "_notify", return_value=True), \
         patch.object(startup.subprocess, "run", side_effect=[
             MagicMock(returncode=0), FileNotFoundError("secret interpreter path"),
         ]):
        assert startup.main() == 1
    records = read_log_records(tmp_path)
    failure = next(record for record in records if record["event"] == "bridge_process_start_failed")
    assert failure["exception"] == "FileNotFoundError"
    assert "secret interpreter path" not in repr(records)
    assert any(record["event"] == "bridge_exit" for record in records)
    assert records[-1]["event"] == "notification_shown"
    assert records[-1]["purpose"] == "bridge_failed"


def test_bridge_environment_reaches_a_child_process_with_dummy_values(monkeypatch):
    import subprocess
    monkeypatch.delenv("OBSIDIAN_BRIDGE_SERVER_URL", raising=False)
    monkeypatch.delenv("OBSIDIAN_BRIDGE_KEY", raising=False)
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    values = {
        "OBSIDIAN_BRIDGE_SERVER_URL": "https://bridge-test.invalid",
        "OBSIDIAN_BRIDGE_KEY": "dummy-key",
        "OBSIDIAN_VAULT_PATH": "/tmp/dummy-vault",
    }
    child_env = startup._bridge_environment(
        values["OBSIDIAN_BRIDGE_SERVER_URL"],
        values["OBSIDIAN_BRIDGE_KEY"],
        values["OBSIDIAN_VAULT_PATH"],
    )
    code = "import os; print(' '.join(str(os.environ.get(k) == v) for k, v in " + repr(values) + ".items()))"
    result = subprocess.run(
        [startup.sys.executable, "-c", code], env=child_env, check=True,
        capture_output=True, text=True,
    )
    assert result.stdout.strip() == "True True True"


def test_startup_configuration_failure_is_classified_without_values(tmp_path):
    with patch.object(startup, "_load_env_file", return_value={}), \
         patch.object(startup, "STARTUP_LOG", tmp_path / "startup.log"), \
         patch.object(startup, "_notify", return_value=True) as notify:
        assert startup.main() == 1
    notify.assert_called_once()
    records = read_log_records(tmp_path)
    assert [record["event"] for record in records] == [
        "startup_started", "notification_shown", "configuration_missing",
    ]


def test_startup_pending_check_failure_is_classified_without_exception_text(tmp_path):
    with patch.object(startup, "_load_env_file", return_value={
        "OBSIDIAN_BRIDGE_SERVER_URL": "https://example.test",
        "OBSIDIAN_BRIDGE_KEY": "secret",
        "OBSIDIAN_VAULT_PATH": "/tmp/vault",
    }), patch.object(startup, "STARTUP_LOG", tmp_path / "startup.log"), \
         patch.object(startup.httpx, "get", side_effect=RuntimeError("secret details")):
        assert startup.main() == 1
    records = read_log_records(tmp_path)
    assert records[-1]["event"] == "pending_check_failed"
    assert records[-1]["exception"] == "RuntimeError"
    assert "secret details" not in repr(records)


def test_startup_pending_http_failure_logs_status_only(tmp_path):
    request = httpx.Request("GET", "https://dummy.invalid/private")
    response = httpx.Response(503, request=request)
    error = httpx.HTTPStatusError("response body with credentials", request=request, response=response)
    with patch.object(startup, "_load_env_file", return_value={
        "OBSIDIAN_BRIDGE_SERVER_URL": "https://dummy.invalid/private",
        "OBSIDIAN_BRIDGE_KEY": "dummy-key",
        "OBSIDIAN_VAULT_PATH": "/tmp/dummy-vault",
    }), patch.object(startup, "STARTUP_LOG", tmp_path / "startup.log"), \
         patch.object(startup.httpx, "get", side_effect=error) as get_mock, \
         patch.object(startup.time, "sleep") as sleep_mock:
        assert startup.main() == 1
    assert get_mock.call_count == len(startup.PENDING_RETRY_DELAYS_SECONDS) + 1
    assert sleep_mock.call_count == len(startup.PENDING_RETRY_DELAYS_SECONDS)
    records = read_log_records(tmp_path)
    assert records[-1]["event"] == "pending_check_failed"
    assert records[-1]["status"] == 503
    retries = [record for record in records if record["event"] == "pending_check_retry"]
    assert len(retries) == len(startup.PENDING_RETRY_DELAYS_SECONDS)
    assert all(record["kind"] == "http_status" for record in retries)
    assert "dummy.invalid" not in repr(records)
    assert "dummy-key" not in repr(records)


def test_startup_retries_transient_timeout_without_bypassing_approval(tmp_path):
    request = httpx.Request("GET", "https://example.test/api/obsidian/pending")
    timeout_error = httpx.ReadTimeout("private URL and credentials", request=request)
    response = MagicMock()
    response.json.return_value = {"ok": True, "pending": True}
    response.raise_for_status.return_value = None
    with patch.object(startup, "_load_env_file", return_value={
        "OBSIDIAN_BRIDGE_SERVER_URL": "https://example.test",
        "OBSIDIAN_BRIDGE_KEY": "dummy-key",
        "OBSIDIAN_VAULT_PATH": "/tmp/dummy-vault",
    }), patch.object(startup, "STARTUP_LOG", tmp_path / "startup.log"), \
         patch.object(startup.httpx, "get", side_effect=[timeout_error, response]) as get_mock, \
         patch.object(startup.time, "sleep") as sleep_mock, \
         patch.object(startup, "_ask_execute", return_value=("later", 0)) as ask_mock, \
         patch.object(startup.subprocess, "run") as run_mock:
        assert startup.main() == 0
    assert get_mock.call_count == 2
    sleep_mock.assert_called_once_with(startup.PENDING_RETRY_DELAYS_SECONDS[0])
    ask_mock.assert_called_once()
    run_mock.assert_not_called()
    records = read_log_records(tmp_path)
    assert [record["event"] for record in records] == [
        "startup_started", "pending_check_retry", "notification_shown", "user_deferred",
    ]
    assert records[1]["exception"] == "ReadTimeout"
    assert "private URL" not in repr(records)
    assert "dummy-key" not in repr(records)


def test_startup_retries_gateway_error_then_checks_pending_state(tmp_path):
    request = httpx.Request("GET", "https://example.test/api/obsidian/pending")
    gateway_response = httpx.Response(503, request=request)
    gateway_error = httpx.HTTPStatusError(
        "private response details", request=request, response=gateway_response
    )
    response = MagicMock()
    response.json.return_value = {"ok": True, "pending": False}
    response.raise_for_status.return_value = None
    with patch.object(startup, "_load_env_file", return_value={
        "OBSIDIAN_BRIDGE_SERVER_URL": "https://example.test",
        "OBSIDIAN_BRIDGE_KEY": "dummy-key",
        "OBSIDIAN_VAULT_PATH": "/tmp/dummy-vault",
    }), patch.object(startup, "STARTUP_LOG", tmp_path / "startup.log"), \
         patch.object(startup.httpx, "get", side_effect=[gateway_error, response]) as get_mock, \
         patch.object(startup.time, "sleep") as sleep_mock, \
         patch.object(startup, "_ask_execute") as ask_mock:
        assert startup.main() == 0
    assert get_mock.call_count == 2
    sleep_mock.assert_called_once_with(startup.PENDING_RETRY_DELAYS_SECONDS[0])
    ask_mock.assert_not_called()
    records = read_log_records(tmp_path)
    assert records[1]["event"] == "pending_check_retry"
    assert records[1]["kind"] == "http_status"
    assert records[1]["status"] == 503
    assert records[-1]["event"] == "pending_none"
    assert "private response details" not in repr(records)
    assert "dummy-key" not in repr(records)


def test_startup_bridge_failure_is_classified_without_environment_values(tmp_path):
    response = MagicMock()
    response.json.return_value = {"ok": True, "pending": True}
    response.raise_for_status.return_value = None
    with patch.object(startup, "_load_env_file", return_value={
        "OBSIDIAN_BRIDGE_SERVER_URL": "https://example.test",
        "OBSIDIAN_BRIDGE_KEY": "secret",
        "OBSIDIAN_VAULT_PATH": "/tmp/vault",
    }), patch.object(startup, "STARTUP_LOG", tmp_path / "startup.log"), \
         patch.object(startup.httpx, "get", return_value=response), \
         patch.object(startup, "_ask_execute", return_value=("execute", 0)), \
         patch.object(startup, "_notify", return_value=True), \
         patch.object(startup, "STARTUP_LOG", tmp_path / "startup.log"), \
         patch.object(startup.subprocess, "run", side_effect=[
             MagicMock(returncode=0), MagicMock(returncode=2, stdout="", stderr=""),
         ]):
        assert startup.main() == 2
    records = read_log_records(tmp_path)
    bridge_exit = next(record for record in records if record["event"] == "bridge_exit")
    diagnostic = next(record for record in records if record["event"] == "bridge_diagnostic")
    assert bridge_exit["exit_code"] == 2
    assert diagnostic["category"] == "bridge_unclassified_failure"
    assert "secret" not in repr(records)
