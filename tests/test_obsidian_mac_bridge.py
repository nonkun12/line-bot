from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from core.obsidian import ObsidianVault
from scripts.obsidian_mac_bridge import BridgeFailure, _validate_server_url, execute_local_job, run_bridge


def test_server_url_validation_allows_https_and_loopback_http():
    for url in (
        "https://example.test",
        "https://vault.example.test:8443/api",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ):
        _validate_server_url(url)


def test_server_url_validation_rejects_non_loopback_http_and_invalid_urls():
    for url in (
        "http://example.test",
        "http://localhost.evil",
        "http://[::1]:8000",
        "https:///missing-host",
        "https://",
        "https://bad host/path",
        "https://%",
        "https://example.test:invalid",
        "https://user:pass@example.test",
        "http://user:pass@localhost",
    ):
        with pytest.raises(ValueError):
            _validate_server_url(url)


def test_run_bridge_rejects_empty_key_and_invalid_vault_before_network(tmp_path):
    with pytest.raises(ValueError, match="bridge_key is required"):
        run_bridge("https://example.test", "  ", str(tmp_path))
    with pytest.raises(ValueError, match="vault_path must be an existing directory"):
        run_bridge("https://example.test", "key", str(tmp_path / "missing"))


def test_run_bridge_classifies_render_http_error_without_sensitive_details(tmp_path, monkeypatch, capsys):
    request = httpx.Request("POST", "https://example.test/api/obsidian/claim")
    response = httpx.Response(503, request=request, content=b"private response body")
    error = httpx.HTTPStatusError("private URL and key", request=request, response=response)
    client = MagicMock()
    client.post.return_value.raise_for_status.side_effect = error
    monkeypatch.setenv("OBSIDIAN_BRIDGE_RUN_ID", "dummy-run-id")

    with patch("scripts.obsidian_mac_bridge.httpx.Client") as client_type:
        client_type.return_value.__enter__.return_value = client
        with pytest.raises(BridgeFailure) as raised:
            run_bridge("https://example.test", "dummy-secret", str(tmp_path))

    assert raised.value.category == "render_http_error"
    assert raised.value.operation == "claim"
    assert raised.value.status == 503
    stderr = capsys.readouterr().err
    assert '"category":"render_http_error"' in stderr
    assert '"run_id":"dummy-run-id"' in stderr
    assert "private response body" not in stderr
    assert "dummy-secret" not in stderr
    assert "example.test" not in stderr


def test_run_bridge_classifies_transport_error_without_sensitive_details(tmp_path):
    client = MagicMock()
    client.post.side_effect = httpx.ConnectError("private connection detail")
    with patch("scripts.obsidian_mac_bridge.httpx.Client") as client_type:
        client_type.return_value.__enter__.return_value = client
        with pytest.raises(BridgeFailure) as raised:
            run_bridge("https://example.test", "dummy-secret", str(tmp_path))
    assert raised.value.category == "render_api_failure"
    assert raised.value.operation == "claim"
    assert raised.value.exception == "ConnectError"


def test_run_bridge_does_not_claim_success_when_completion_response_is_invalid(tmp_path, capsys):
    claim = MagicMock()
    claim.json.return_value = {
        "job": {"id": 12, "claim_token": "dummy-claim-token", "user_id": "U-dummy",
                "message": "Obsidianに保存 notes/safe.md: dummy-body"}
    }
    claim.raise_for_status.return_value = None
    completion = MagicMock()
    completion.json.return_value = {"ok": True, "status": "unknown"}
    completion.raise_for_status.return_value = None
    client = MagicMock()
    client.post.side_effect = [claim, completion]

    with patch("scripts.obsidian_mac_bridge.httpx.Client") as client_type, \
         patch("scripts.obsidian_mac_bridge.execute_local_job", return_value={"success": True, "reply": "saved"}):
        client_type.return_value.__enter__.return_value = client
        with pytest.raises(BridgeFailure) as raised:
            run_bridge("https://example.test", "dummy-secret", str(tmp_path))

    assert raised.value.category == "render_response_invalid"
    assert raised.value.operation == "complete"
    stderr = capsys.readouterr().err
    assert "dummy-claim-token" not in stderr
    assert "dummy-secret" not in stderr
    assert "dummy-body" not in stderr
    assert '"reason":"invalid_completion_result"' in stderr


def test_run_bridge_accepts_only_matching_completion_response(tmp_path, capsys):
    claim = MagicMock()
    claim.json.return_value = {
        "job": {"id": 12, "claim_token": "dummy-claim-token", "user_id": "U-dummy",
                "message": "Obsidianに保存 notes/safe.md: dummy-body"}
    }
    claim.raise_for_status.return_value = None
    completion = MagicMock()
    completion.json.return_value = {"ok": True, "status": "completed"}
    completion.raise_for_status.return_value = None
    client = MagicMock()
    client.post.side_effect = [claim, completion]

    with patch("scripts.obsidian_mac_bridge.httpx.Client") as client_type, \
         patch("scripts.obsidian_mac_bridge.execute_local_job", return_value={"success": True, "reply": "saved"}):
        client_type.return_value.__enter__.return_value = client
        run_bridge("https://example.test", "dummy-secret", str(tmp_path))

    assert '"category":"job_completed"' in capsys.readouterr().err
    completion_data = client.post.call_args_list[1].kwargs["json"]
    assert completion_data["success"] is True


def test_run_bridge_classifies_local_write_failure_without_sensitive_details(tmp_path, capsys):
    claim = MagicMock()
    claim.json.return_value = {"job": {
        "id": 12, "claim_token": "dummy-claim-token", "user_id": "dummy-user",
        "message": "Obsidianに保存 notes/safe.md: dummy-job-body",
    }}
    claim.raise_for_status.return_value = None
    completion = MagicMock()
    completion.json.return_value = {"ok": True, "status": "failed"}
    completion.raise_for_status.return_value = None
    client = MagicMock()
    client.post.side_effect = [claim, completion]

    with patch("scripts.obsidian_mac_bridge.httpx.Client") as client_type, \
         patch("scripts.obsidian_mac_bridge.execute_local_job", side_effect=PermissionError("private path")):
        client_type.return_value.__enter__.return_value = client
        run_bridge("https://example.test", "dummy-secret", str(tmp_path))

    stderr = capsys.readouterr().err
    assert '"category":"vault_write_failed"' in stderr
    assert "private path" not in stderr
    assert "dummy-job-body" not in stderr
    assert "dummy-claim-token" not in stderr
    assert "dummy-secret" not in stderr
    completion_data = client.post.call_args_list[1].kwargs["json"]
    assert completion_data["error"] == "local operation failed (PermissionError)"
    assert completion_data["diagnostic_category"] == "vault_write_failed"
    assert completion_data["diagnostic_detail"] == "PermissionError"


def test_execute_local_job_uses_the_guarded_agent(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    result = execute_local_job(
        {"id": 1, "user_id": "U1",
         "message": "Obsidianに保存 notes/todo.md: bridge works", "claim_token": "token"},
        str(vault),
    )
    assert result["success"] is True
    assert "保存しました" in result["reply"]
    assert (vault / "notes/todo.md").read_text(encoding="utf-8") == "bridge works"


def test_execute_local_job_fails_closed_for_invalid_message(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    with pytest.raises(ValueError, match="message is required"):
        execute_local_job(
            {"id": 1, "user_id": "U1", "message": "", "claim_token": "token"},
            str(vault),
        )


def test_execute_local_job_uses_same_safe_path_contract(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    target = vault / "notes" / "todo.md"
    target.parent.mkdir()
    target.write_text("existing", encoding="utf-8")
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    result = execute_local_job(
        {"id": 2, "user_id": "U1",
         "message": "Obsidianに保存 notes/todo.md: overwrite", "claim_token": "token"},
        str(vault),
    )
    assert result["success"] is False
    assert "上書き" in result["reply"]
    assert target.read_text(encoding="utf-8") == "existing"
    assert ObsidianVault(vault).read_note("notes/todo.md") == "existing"
