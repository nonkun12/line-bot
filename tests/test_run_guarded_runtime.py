import hashlib
import json

import pytest

from scripts import run_guarded_runtime as guarded_runtime
from scripts.run_guarded_runtime import guarded_ask


def _bind_policy_catalog_digest(report_path, catalog_path):
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["admitted_catalog_sha256"] = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    report_path.write_text(json.dumps(report), encoding="utf-8")


def test_run_local_policy_catalog_requires_exact_task_path_and_base_sha(monkeypatch, tmp_path):
    from scripts.autonomous_task_target_allowlist import TARGETS

    task_id = "review-coverage-gap-0123456789"
    test_path = TARGETS[0][1]
    base_sha = "a" * 40
    instruction = "Append one deterministic pytest test."
    report_path = tmp_path / "policy-report.json"
    catalog_path = tmp_path / "policy-catalog.json"
    report_path.write_text(json.dumps({
        "status": "POLICY_ADMITTED",
        "admitted_task_id": task_id,
        "admitted_allowed_path": test_path,
        "base_sha": base_sha,
    }), encoding="utf-8")
    catalog_path.write_text(json.dumps({"tasks": [{
        "id": task_id,
        "instruction": instruction,
        "allowed_paths": [test_path],
        "execution_approved": True,
    }]}), encoding="utf-8")
    _bind_policy_catalog_digest(report_path, catalog_path)
    monkeypatch.setattr(guarded_runtime, "POLICY_ADMISSION_REPORT_PATH", report_path)
    monkeypatch.setattr(guarded_runtime, "POLICY_ADMISSION_CATALOG_PATH", catalog_path)
    monkeypatch.setenv("AUTONOMOUS_TEST_ADMISSION_POLICY", "true")
    monkeypatch.setenv("AUTONOMOUS_LOOP_TASK_CATALOG", str(catalog_path))
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", task_id)
    monkeypatch.setenv("AUTONOMOUS_ALLOWED_PATHS", json.dumps([test_path]))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setenv("GITHUB_REPOSITORY", "nonkun12/line-bot")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_ACTOR", "nonkun12")

    result = guarded_runtime._verify_catalog_execution_approval(base_sha, instruction)

    assert result["gate"] == "PASS"
    assert result["execution_authorized"] is True
    assert result["task_id"] == task_id
    assert result["scope"] == "run_local_test_policy"


def test_run_local_policy_catalog_accepts_only_scheduler_dispatch(monkeypatch, tmp_path):
    from scripts.autonomous_task_target_allowlist import TARGETS

    task_id = "review-coverage-gap-0123456789"
    test_path = TARGETS[0][1]
    base_sha = "c" * 40
    instruction = "Append one deterministic pytest test."
    report_path = tmp_path / "policy-report.json"
    catalog_path = tmp_path / "policy-catalog.json"
    event_path = tmp_path / "event.json"
    report_path.write_text(json.dumps({
        "status": "POLICY_ADMITTED",
        "admitted_task_id": task_id,
        "admitted_allowed_path": test_path,
        "base_sha": base_sha,
    }), encoding="utf-8")
    catalog_path.write_text(json.dumps({"tasks": [{
        "id": task_id,
        "instruction": instruction,
        "allowed_paths": [test_path],
        "execution_approved": True,
    }]}), encoding="utf-8")
    event_path.write_text(json.dumps({
        "sender": {"login": "github-actions[bot]"},
        "inputs": {
            "policy_dispatch": "30m_scheduler",
            "max_tasks": "1",
            "execution_approval": "DENY",
        },
    }), encoding="utf-8")
    _bind_policy_catalog_digest(report_path, catalog_path)
    monkeypatch.setattr(guarded_runtime, "POLICY_ADMISSION_REPORT_PATH", report_path)
    monkeypatch.setattr(guarded_runtime, "POLICY_ADMISSION_CATALOG_PATH", catalog_path)
    monkeypatch.setenv("AUTONOMOUS_TEST_ADMISSION_POLICY", "true")
    monkeypatch.setenv("AUTONOMOUS_LOOP_TASK_CATALOG", str(catalog_path))
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", task_id)
    monkeypatch.setenv("AUTONOMOUS_ALLOWED_PATHS", json.dumps([test_path]))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "nonkun12/line-bot")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_ACTOR", "github-actions[bot]")

    monkeypatch.setenv("AUTONOMOUS_POLICY_DISPATCH_SOURCE", "30m_scheduler")

    result = guarded_runtime._verify_execution_approval(base_sha, instruction)

    assert result["gate"] == "PASS"
    assert result["scope"] == "run_local_test_policy"


def test_scheduler_dispatch_still_accepts_reviewed_catalog_task(monkeypatch, tmp_path):
    task_id = "reviewed-task"
    test_path = "tests/test_stocks.py"
    base_sha = "e" * 40
    instruction = "Run the reviewed test task."
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps({
        "sender": {"login": "github-actions[bot]"},
        "inputs": {
            "policy_dispatch": "30m_scheduler",
            "max_tasks": "1",
            "execution_approval": "DENY",
        },
    }), encoding="utf-8")
    catalog = {"tasks": [{
        "id": task_id,
        "instruction": instruction,
        "allowed_paths": [test_path],
        "execution_approved": True,
    }]}
    monkeypatch.setattr(guarded_runtime, "_git", lambda *args: json.dumps(catalog))
    monkeypatch.setenv("AUTONOMOUS_TEST_ADMISSION_POLICY", "false")
    monkeypatch.setenv("AUTONOMOUS_POLICY_DISPATCH_SOURCE", "30m_scheduler")
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", task_id)
    monkeypatch.setenv("AUTONOMOUS_ALLOWED_PATHS", json.dumps([test_path]))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "nonkun12/line-bot")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_ACTOR", "github-actions[bot]")

    result = guarded_runtime._verify_execution_approval(base_sha, instruction)

    assert result["gate"] == "PASS"
    assert result["scope"] == "catalog_preapproved_execution"


def test_run_local_policy_catalog_rejects_user_spoofed_scheduler_dispatch(monkeypatch, tmp_path):
    from scripts.autonomous_task_target_allowlist import TARGETS

    task_id = "review-coverage-gap-0123456789"
    test_path = TARGETS[0][1]
    catalog_path = tmp_path / "policy-catalog.json"
    report_path = tmp_path / "policy-report.json"
    event_path = tmp_path / "event.json"
    report_path.write_text(json.dumps({
        "status": "POLICY_ADMITTED",
        "admitted_task_id": task_id,
        "admitted_allowed_path": test_path,
        "base_sha": "d" * 40,
    }), encoding="utf-8")
    catalog_path.write_text(json.dumps({"tasks": [{
        "id": task_id,
        "instruction": "Append one deterministic pytest test.",
        "allowed_paths": [test_path],
        "execution_approved": True,
    }]}), encoding="utf-8")
    event_path.write_text(json.dumps({
        "sender": {"login": "nonkun12"},
        "inputs": {"policy_dispatch": "30m_scheduler", "max_tasks": "1"},
    }), encoding="utf-8")
    _bind_policy_catalog_digest(report_path, catalog_path)
    monkeypatch.setattr(guarded_runtime, "POLICY_ADMISSION_REPORT_PATH", report_path)
    monkeypatch.setattr(guarded_runtime, "POLICY_ADMISSION_CATALOG_PATH", catalog_path)
    monkeypatch.setenv("AUTONOMOUS_TEST_ADMISSION_POLICY", "true")
    monkeypatch.setenv("AUTONOMOUS_LOOP_TASK_CATALOG", str(catalog_path))
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", task_id)
    monkeypatch.setenv("AUTONOMOUS_ALLOWED_PATHS", json.dumps([test_path]))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "nonkun12/line-bot")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_ACTOR", "nonkun12")

    result = guarded_runtime._verify_catalog_execution_approval("d" * 40, "Append one deterministic pytest test.")

    assert result["gate"] == "BLOCKED"
    assert result["execution_authorized"] is False


def test_run_local_policy_catalog_rejects_stale_base_sha(monkeypatch, tmp_path):
    from scripts.autonomous_task_target_allowlist import TARGETS

    task_id = "review-coverage-gap-0123456789"
    test_path = TARGETS[0][1]
    catalog_path = tmp_path / "policy-catalog.json"
    report_path = tmp_path / "policy-report.json"
    report_path.write_text(json.dumps({
        "status": "POLICY_ADMITTED",
        "admitted_task_id": task_id,
        "admitted_allowed_path": test_path,
        "base_sha": "b" * 40,
    }), encoding="utf-8")
    catalog_path.write_text(json.dumps({"tasks": [{
        "id": task_id,
        "instruction": "Append one deterministic pytest test.",
        "allowed_paths": [test_path],
        "execution_approved": True,
    }]}), encoding="utf-8")
    _bind_policy_catalog_digest(report_path, catalog_path)
    monkeypatch.setattr(guarded_runtime, "POLICY_ADMISSION_REPORT_PATH", report_path)
    monkeypatch.setattr(guarded_runtime, "POLICY_ADMISSION_CATALOG_PATH", catalog_path)
    monkeypatch.setenv("AUTONOMOUS_TEST_ADMISSION_POLICY", "true")
    monkeypatch.setenv("AUTONOMOUS_LOOP_TASK_CATALOG", str(catalog_path))
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", task_id)
    monkeypatch.setenv("AUTONOMOUS_ALLOWED_PATHS", json.dumps([test_path]))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setenv("GITHUB_REPOSITORY", "nonkun12/line-bot")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_ACTOR", "nonkun12")

    result = guarded_runtime._verify_catalog_execution_approval("a" * 40, "Append one deterministic pytest test.")

    assert result["gate"] == "BLOCKED"
    assert result["execution_authorized"] is False

class _Message:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Response:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return _Response(response)


class _Client:
    def __init__(self, responses):
        self.completions = _Completions(responses)
        self.chat = type("Chat", (), {"completions": self.completions})()


def test_guarded_ask_retries_invalid_json_and_returns_object():
    client = _Client(["not json", '{"file":"tests/test_management_router.py"}'])

    content = guarded_ask(client, "return JSON", "select a file")

    assert json.loads(content) == {"file": "tests/test_management_router.py"}
    assert len(client.completions.calls) == 2
    assert client.completions.calls[0]["response_format"] == {"type": "json_object"}
    assert "single valid JSON object only" in client.completions.calls[1]["messages"][0]["content"]


def test_guarded_ask_retries_empty_response():
    client = _Client(["", '{"file":null}'])

    content = guarded_ask(client, "return JSON", "select a file")

    assert json.loads(content) == {"file": None}
    assert len(client.completions.calls) == 2


def test_guarded_ask_fails_closed_after_three_bad_responses():
    client = _Client(["not json", "still not json", "also not json"])

    with pytest.raises(ValueError, match="unusable after bounded JSON retry"):
        guarded_ask(client, "return JSON", "select a file")

    assert len(client.completions.calls) == 3


def test_guarded_ask_rejects_non_object_json():
    client = _Client(["[1,2,3]", '{"file":"tests/test_management_router.py"}'])

    content = guarded_ask(client, "return JSON", "select a file")

    assert json.loads(content) == {"file": "tests/test_management_router.py"}
    assert len(client.completions.calls) == 2


def test_guarded_ask_recovers_on_third_attempt_and_uses_stricter_prompt():
    client = _Client([
        "not json",
        "still not json",
        '{"file":"tests/test_management_router.py"}',
    ])

    content = guarded_ask(client, "return JSON", "select a file")

    assert json.loads(content) == {"file": "tests/test_management_router.py"}
    assert len(client.completions.calls) == 3
    assert "smallest valid JSON object" in client.completions.calls[2]["messages"][0]["content"]



class _ProviderError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.body = {"error": {"code": code, "message": "provider JSON validation failed"}}


def test_guarded_ask_retries_provider_json_validate_failed():
    client = _Client([
        _ProviderError("json_validate_failed"),
        '{"file":"tests/test_catalog_exhaustion_analyzer.py"}',
    ])

    content = guarded_ask(client, "return JSON", "select a file")

    assert json.loads(content) == {"file": "tests/test_catalog_exhaustion_analyzer.py"}
    assert len(client.completions.calls) == 2
    assert "single valid JSON object only" in client.completions.calls[1]["messages"][0]["content"]


def test_guarded_ask_does_not_retry_other_provider_errors():
    client = _Client([_ProviderError("rate_limit_exceeded"), '{"file":null}'])

    with pytest.raises(_ProviderError):
        guarded_ask(client, "return JSON", "select a file")

    assert len(client.completions.calls) == 1


def test_guarded_ask_fails_closed_after_three_provider_json_validate_failures():
    client = _Client([
        _ProviderError("json_validate_failed"),
        _ProviderError("json_validate_failed"),
        _ProviderError("json_validate_failed"),
    ])

    with pytest.raises(ValueError, match="unusable after bounded JSON retry"):
        guarded_ask(client, "return JSON", "select a file")

    assert len(client.completions.calls) == 3


def test_common_runtime_rea_block_prevents_development_execution(monkeypatch, tmp_path):
    sha = "a" * 40
    rea = {
        "gate": "BLOCKED",
        "reason_code": "rea_high_or_critical_finding",
        "target_sha": sha,
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }
    monkeypatch.setattr(guarded_runtime, "_git", lambda *args: sha)
    monkeypatch.setattr(
        "scripts.rea_control_tower_adapter.prepare_rea_evidence",
        lambda root, expected_sha: rea,
    )
    monkeypatch.setattr(
        guarded_runtime.runtime,
        "execute",
        lambda instruction: (_ for _ in ()).throw(AssertionError("runtime must not execute")),
    )
    summary_path = tmp_path / "summary.json"
    monkeypatch.setenv("AUTONOMOUS_SUMMARY_PATH", str(summary_path))
    monkeypatch.delenv("GITHUB_ENV", raising=False)

    assert guarded_runtime.main() == 80
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "BLOCKED"
    assert summary["exit_code"] == 80
    assert summary["rea"] == rea


def test_common_runtime_rea_adapter_exception_blocks_development_execution(monkeypatch, tmp_path):
    sha = "a" * 40
    rea = {
        "gate": "BLOCKED",
        "reason_code": "rea_high_or_critical_finding",
        "target_sha": sha,
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }
    monkeypatch.setattr(guarded_runtime, "_git", lambda *args: sha)
    monkeypatch.setattr(
        "scripts.rea_control_tower_adapter.prepare_rea_evidence",
        lambda root, expected_sha: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        guarded_runtime.runtime,
        "execute",
        lambda instruction: (_ for _ in ()).throw(AssertionError("runtime must not execute")),
    )
    summary_path = tmp_path / "summary.json"
    monkeypatch.setenv("AUTONOMOUS_SUMMARY_PATH", str(summary_path))
    monkeypatch.delenv("GITHUB_ENV", raising=False)

    assert guarded_runtime.main() == 80
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "BLOCKED"
    assert summary["exit_code"] == 80
    assert summary["rea"]["reason_code"] == "rea_adapter_error"
    assert summary["rea"]["execution_authorized"] is False


def test_common_runtime_records_rea_evidence_on_success(monkeypatch, tmp_path):
    sha = "b" * 40
    rea = {
        "gate": "PASS",
        "mode": "OBSERVE_ONLY",
        "target_sha": sha,
        "scanner_status": "PASS",
        "finding_count": 0,
        "findings_truncated": False,
        "findings": [],
        "critical_count": 0,
        "blocking_count": 0,
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }
    monkeypatch.setattr(
        guarded_runtime,
        "_git",
        lambda *args: sha if args == ("rev-parse", "HEAD") else "test-branch",
    )
    monkeypatch.setattr(
        "scripts.rea_control_tower_adapter.prepare_rea_evidence",
        lambda root, expected_sha: rea,
    )
    monkeypatch.setattr(guarded_runtime, "_augment_instruction_with_history", lambda instruction, path: instruction)
    monkeypatch.setattr(guarded_runtime, "_augment_with_hermes_advice", lambda instruction, path: instruction)
    monkeypatch.setattr(guarded_runtime, "_shared_stop_active", lambda: False)
    monkeypatch.setattr(guarded_runtime.runtime, "execute", lambda instruction: 0)
    monkeypatch.setenv("AUTONOMOUS_SUMMARY_PATH", str(tmp_path / "summary.json"))
    instruction = "safe test instruction"
    monkeypatch.setenv("DEV_INSTRUCTION", instruction)
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "rsi-test-task")
    monkeypatch.setenv("AUTONOMOUS_ALLOWED_PATHS", json.dumps(["tests/test_run_guarded_runtime.py"]))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_ACTOR", "nonkun12")
    monkeypatch.setenv("GITHUB_REPOSITORY", "nonkun12/line-bot")
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps({"sender": {"login": "nonkun12"}, "repository": {"full_name": "nonkun12/line-bot"}, "inputs": {"execution_approval": "APPROVE_EXECUTION", "approval_task_id": "rsi-test-task", "approval_instruction_sha256": hashlib.sha256(instruction.encode()).hexdigest(), "approval_base_sha": sha, "approval_allowed_paths_sha256": hashlib.sha256(json.dumps(["tests/test_run_guarded_runtime.py"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.delenv("GITHUB_ENV", raising=False)

    monkeypatch.setattr(
        guarded_runtime,
        "_consume_execution_approval",
        lambda evidence, start_sha: {"gate": "PASS", "reason_code": "approval_consumed_once", "marker_ref": "refs/heads/rsi-approval-consumed/test", "marker_sha": start_sha},
    )
    assert guarded_runtime.main() == 0
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "PASS"
    assert summary["rea"] == rea
    assert summary["execution_approval"]["gate"] == "PASS"
    assert summary["execution_approval"]["scope"] == "execution"




def test_common_runtime_blocks_when_shared_stop_status_is_unavailable(monkeypatch, tmp_path):
    sha = "d" * 40
    rea = {"gate": "PASS", "target_sha": sha, "scanner_status": "PASS", "finding_count": 0, "critical_count": 0, "blocking_count": 0, "findings": [], "execution_authorized": False, "patch_authorized": False, "hold_clear_authorized": False, "merge_deploy_authorized": False}
    monkeypatch.setattr(guarded_runtime, "_git", lambda *args: sha if args == ("rev-parse", "HEAD") else "test-branch")
    monkeypatch.setattr("scripts.rea_control_tower_adapter.prepare_rea_evidence", lambda root, expected_sha: rea)
    monkeypatch.setattr("scripts.rea_control_tower_adapter.rea_evidence_is_valid_pass", lambda evidence, expected_sha: True)
    monkeypatch.setattr(guarded_runtime, "_shared_stop_active", lambda: (_ for _ in ()).throw(RuntimeError("unavailable")))
    monkeypatch.setattr(guarded_runtime.runtime, "execute", lambda instruction: (_ for _ in ()).throw(AssertionError("runtime must not execute")))
    path = tmp_path / "summary.json"
    monkeypatch.setenv("AUTONOMOUS_SUMMARY_PATH", str(path))
    monkeypatch.delenv("GITHUB_ENV", raising=False)
    assert guarded_runtime.main() == 82
    summary = json.loads(path.read_text(encoding="utf-8"))
    assert summary["status"] == "BLOCKED"
    assert summary["execution_approval"]["reason_code"] == "shared_stop_status_unconfirmed"


def test_common_runtime_blocks_when_shared_stop_is_active(monkeypatch, tmp_path):
    sha = "e" * 40
    rea = {"gate": "PASS", "target_sha": sha, "scanner_status": "PASS", "finding_count": 0, "critical_count": 0, "blocking_count": 0, "findings": [], "execution_authorized": False, "patch_authorized": False, "hold_clear_authorized": False, "merge_deploy_authorized": False}
    monkeypatch.setattr(guarded_runtime, "_git", lambda *args: sha if args == ("rev-parse", "HEAD") else "test-branch")
    monkeypatch.setattr("scripts.rea_control_tower_adapter.prepare_rea_evidence", lambda root, expected_sha: rea)
    monkeypatch.setattr("scripts.rea_control_tower_adapter.rea_evidence_is_valid_pass", lambda evidence, expected_sha: True)
    monkeypatch.setattr(guarded_runtime, "_shared_stop_active", lambda: True)
    monkeypatch.setattr(guarded_runtime.runtime, "execute", lambda instruction: (_ for _ in ()).throw(AssertionError("runtime must not execute")))
    path = tmp_path / "summary.json"
    monkeypatch.setenv("AUTONOMOUS_SUMMARY_PATH", str(path))
    monkeypatch.delenv("GITHUB_ENV", raising=False)
    assert guarded_runtime.main() == 82
    summary = json.loads(path.read_text(encoding="utf-8"))
    assert summary["status"] == "BLOCKED"
    assert summary["execution_approval"]["reason_code"] == "emergency_stop_active"

def test_write_summary_preserves_only_allowlisted_failure_code(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTONOMOUS_FAILURE_CODE", "existing_test_modified_repair_failed")
    monkeypatch.setattr(
        guarded_runtime,
        "_git",
        lambda *args: "a" * 40 if args[0] == "rev-parse" else "main",
    )
    summary = tmp_path / "summary.json"

    guarded_runtime._write_summary("FAIL", 1, "a" * 40, summary)

    assert json.loads(summary.read_text(encoding="utf-8"))["failure_code"] == "existing_test_modified_repair_failed"


def test_write_summary_drops_untrusted_failure_text(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTONOMOUS_FAILURE_CODE", "secret=do-not-copy")
    monkeypatch.setattr(
        guarded_runtime,
        "_git",
        lambda *args: "a" * 40 if args[0] == "rev-parse" else "main",
    )
    summary = tmp_path / "summary.json"

    guarded_runtime._write_summary("FAIL", 1, "a" * 40, summary)

    assert "failure_code" not in json.loads(summary.read_text(encoding="utf-8"))


def test_common_runtime_blocks_without_independent_approval_even_if_env_claims_approval(monkeypatch, tmp_path):
    sha = "c" * 40
    rea = {"gate": "PASS", "target_sha": sha, "scanner_status": "PASS", "finding_count": 0, "critical_count": 0, "blocking_count": 0, "findings": [], "execution_authorized": False, "patch_authorized": False, "hold_clear_authorized": False, "merge_deploy_authorized": False}
    monkeypatch.setattr(guarded_runtime, "_git", lambda *args: sha if args == ("rev-parse", "HEAD") else "test-branch")
    monkeypatch.setattr("scripts.rea_control_tower_adapter.prepare_rea_evidence", lambda root, expected_sha: rea)
    monkeypatch.setattr("scripts.rea_control_tower_adapter.rea_evidence_is_valid_pass", lambda evidence, expected_sha: True)
    monkeypatch.setattr(guarded_runtime.runtime, "execute", lambda instruction: (_ for _ in ()).throw(AssertionError("runtime must not execute")))
    monkeypatch.setattr(guarded_runtime, "_shared_stop_active", lambda: False)
    monkeypatch.setenv("AUTONOMOUS_SUMMARY_PATH", str(tmp_path / "summary.json"))
    monkeypatch.setenv("DEV_INSTRUCTION", "safe test instruction")
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "rsi-test-task")
    monkeypatch.setenv("AUTONOMOUS_EXECUTION_APPROVED", "true")
    monkeypatch.setenv("EXECUTION_APPROVED", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    monkeypatch.delenv("GITHUB_ENV", raising=False)
    assert guarded_runtime.main() == 81
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "BLOCKED"
    assert summary["exit_code"] == 81
    assert summary["execution_approval"]["gate"] == "BLOCKED"
    assert summary["execution_approval"]["execution_authorized"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sender", {"login": "someone-else"}),
        ("repository", {"full_name": "someone-else/line-bot"}),
        ("approval_task_id", "different-task"),
        ("approval_instruction_sha256", "0" * 64),
        ("approval_base_sha", "d" * 40),
        ("approval_allowed_paths_sha256", "0" * 64),
    ],
)
def test_execution_approval_rejects_mismatched_binding(tmp_path, monkeypatch, field, value):
    instruction = "bound task instruction"
    base_sha = "e" * 40
    event = {
        "sender": {"login": "nonkun12"},
        "repository": {"full_name": "nonkun12/line-bot"},
        "inputs": {
            "execution_approval": "APPROVE_EXECUTION",
            "approval_task_id": "bound-task",
            "approval_instruction_sha256": hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
            "approval_base_sha": base_sha,
            "approval_allowed_paths_sha256": hashlib.sha256(json.dumps(["tests/test_run_guarded_runtime.py"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest(),
        },
    }
    if field in {"sender", "repository"}:
        event[field] = value
    else:
        event["inputs"][field] = value
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_ACTOR", "nonkun12")
    monkeypatch.setenv("GITHUB_REPOSITORY", "nonkun12/line-bot")
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "bound-task")
    monkeypatch.setenv("AUTONOMOUS_ALLOWED_PATHS", json.dumps(["tests/test_run_guarded_runtime.py"]))

    evidence = guarded_runtime._verify_execution_approval(base_sha, instruction)

    assert evidence["gate"] == "BLOCKED"
    assert evidence["execution_authorized"] is False


@pytest.mark.parametrize(
    ("comment_body", "is_pull_request"),
    [
        (
            "/distributed-loop resume_task_id=bound-task confirm_cause_fixed=true reviewed=true",
            True,
        ),
        (
            "/distributed-loop resume_task_id=other-task confirm_cause_fixed=true reviewed=true",
            True,
        ),
        (
            "/distributed-loop resume_task_id=bound-task confirm_cause_fixed=true",
            True,
        ),
        (
            "/distributed-loop resume_task_id=bound-task confirm_cause_fixed=true reviewed=true",
            False,
        ),
    ],
)
def test_single_comment_execution_approval_is_task_bound_and_requires_exact_pr_command(
    tmp_path, monkeypatch, comment_body, is_pull_request
):
    instruction = "bound task instruction"
    base_sha = "e" * 40
    event = {
        "sender": {"login": "nonkun12"},
        "repository": {"full_name": "nonkun12/line-bot"},
        "issue": (
            {"pull_request": {"url": "https://api.github.com/repos/nonkun12/line-bot/pulls/1557"}}
            if is_pull_request
            else {}
        ),
        "comment": {"body": comment_body},
    }
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issue_comment")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_ACTOR", "nonkun12")
    monkeypatch.setenv("GITHUB_REPOSITORY", "nonkun12/line-bot")
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "bound-task")
    monkeypatch.setenv("AUTONOMOUS_ALLOWED_PATHS", json.dumps(["tests/test_run_guarded_runtime.py"]))

    evidence = guarded_runtime._verify_execution_approval(base_sha, instruction)

    if comment_body.endswith("reviewed=true") and is_pull_request and "resume_task_id=bound-task " in comment_body:
        assert evidence["gate"] == "PASS"
        assert evidence["execution_authorized"] is True
        assert evidence["task_id"] == "bound-task"
        assert evidence["instruction_sha256"] == hashlib.sha256(instruction.encode("utf-8")).hexdigest()
        assert evidence["allowed_paths_sha256"] == hashlib.sha256(
            json.dumps(["tests/test_run_guarded_runtime.py"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        assert evidence["base_sha"] == base_sha
    else:
        assert evidence["gate"] == "BLOCKED"
        assert evidence["execution_authorized"] is False


def test_execution_approval_rejects_actor_environment_mismatch(tmp_path, monkeypatch):
    instruction = "bound task instruction"
    base_sha = "f" * 40
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps({
            "sender": {"login": "nonkun12"},
            "repository": {"full_name": "nonkun12/line-bot"},
            "inputs": {
                "execution_approval": "APPROVE_EXECUTION",
                "approval_task_id": "bound-task",
                "approval_instruction_sha256": hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
                "approval_base_sha": base_sha,
            "approval_allowed_paths_sha256": hashlib.sha256(json.dumps(["tests/test_run_guarded_runtime.py"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest(),
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_ACTOR", "someone-else")
    monkeypatch.setenv("GITHUB_REPOSITORY", "nonkun12/line-bot")
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "bound-task")
    monkeypatch.setenv("AUTONOMOUS_ALLOWED_PATHS", json.dumps(["tests/test_run_guarded_runtime.py"]))

    evidence = guarded_runtime._verify_execution_approval(base_sha, instruction)

    assert evidence["gate"] == "BLOCKED"
    assert evidence["execution_authorized"] is False

def test_execution_approval_rejects_dispatch_from_non_default_branch(tmp_path, monkeypatch):
    instruction = "bound task instruction"
    base_sha = "9" * 40
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps({
            "sender": {"login": "nonkun12"},
            "repository": {"full_name": "nonkun12/line-bot"},
            "inputs": {
                "execution_approval": "APPROVE_EXECUTION",
                "approval_task_id": "bound-task",
                "approval_instruction_sha256": hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
                "approval_base_sha": base_sha,
            "approval_allowed_paths_sha256": hashlib.sha256(json.dumps(["tests/test_run_guarded_runtime.py"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest(),
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_REF", "refs/heads/unreviewed-feature")
    monkeypatch.setenv("GITHUB_ACTOR", "nonkun12")
    monkeypatch.setenv("GITHUB_REPOSITORY", "nonkun12/line-bot")
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "bound-task")
    monkeypatch.setenv("AUTONOMOUS_ALLOWED_PATHS", json.dumps(["tests/test_run_guarded_runtime.py"]))

    evidence = guarded_runtime._verify_execution_approval(base_sha, instruction)

    assert evidence["gate"] == "BLOCKED"
    assert evidence["execution_authorized"] is False



def test_execution_approval_consumption_requires_github_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    evidence = {
        "execution_authorized": True,
        "actor": "nonkun12",
        "task_id": "task-1",
        "instruction_sha256": "a" * 64,
    }
    result = guarded_runtime._consume_execution_approval(evidence, "b" * 40)
    assert result["gate"] == "BLOCKED"
    assert result["reason_code"] == "approval_ledger_token_missing"


def test_execution_approval_consumption_blocks_duplicate_ref(monkeypatch):
    import urllib.error

    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    def duplicate_ref(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 422, "already exists", {}, None)

    monkeypatch.setattr(guarded_runtime.urllib.request, "urlopen", duplicate_ref)
    evidence = {
        "execution_authorized": True,
        "actor": "nonkun12",
        "task_id": "task-1",
        "instruction_sha256": "a" * 64,
        "allowed_paths_sha256": "c" * 64,
    }
    result = guarded_runtime._consume_execution_approval(evidence, "b" * 40)
    assert result["gate"] == "BLOCKED"
    assert result["reason_code"] == "approval_already_consumed"


def test_write_summary_marks_post_generation_rea_as_pre_publish_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(guarded_runtime, "_git", lambda *args: "b" * 40 if args == ("rev-parse", "HEAD") else "line-dev/test")
    monkeypatch.setenv("AUTONOMOUS_POSTGEN_REA_STATUS", "PASS")
    monkeypatch.setenv("AUTONOMOUS_POSTGEN_REA_BASE_SHA", "a" * 40)
    monkeypatch.setenv("AUTONOMOUS_POSTGEN_REA_TARGET_SHA", "b" * 40)
    monkeypatch.setenv("AUTONOMOUS_POSTGEN_REA_DIFF_SHA256", "c" * 64)
    monkeypatch.delenv("GITHUB_ENV", raising=False)
    path = tmp_path / "summary.json"

    guarded_runtime._write_summary("PASS", 0, "a" * 40, path)

    postgen = json.loads(path.read_text(encoding="utf-8"))["post_generation_rea"]
    assert postgen["diagnostic_only"] is False
    assert postgen["gate_stage"] == "pre_publish"
    assert postgen["publish_gate_passed"] is True


def test_write_summary_never_reports_publish_gate_pass_after_runtime_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(guarded_runtime, "_git", lambda *args: "b" * 40 if args == ("rev-parse", "HEAD") else "line-dev/test")
    monkeypatch.setenv("AUTONOMOUS_POSTGEN_REA_STATUS", "PASS")
    monkeypatch.setenv("AUTONOMOUS_POSTGEN_REA_BASE_SHA", "a" * 40)
    monkeypatch.setenv("AUTONOMOUS_POSTGEN_REA_TARGET_SHA", "b" * 40)
    monkeypatch.setenv("AUTONOMOUS_POSTGEN_REA_DIFF_SHA256", "c" * 64)
    monkeypatch.delenv("GITHUB_ENV", raising=False)
    path = tmp_path / "summary.json"

    guarded_runtime._write_summary("FAIL", 1, "a" * 40, path)

    postgen = json.loads(path.read_text(encoding="utf-8"))["post_generation_rea"]
    assert postgen["diagnostic_only"] is False
    assert postgen["gate_stage"] == "pre_publish"
    assert postgen["publish_gate_passed"] is False


def test_execution_approval_accepts_workflow_prepared_line_dispatch(tmp_path, monkeypatch):
    instruction = "implement a safe bounded feature"
    base_sha = "9" * 40
    paths = ["tests/test_run_guarded_runtime.py"]
    canonical_paths = json.dumps(paths, ensure_ascii=False, separators=(",", ":"))
    instruction_digest = hashlib.sha256(instruction.encode("utf-8")).hexdigest()
    paths_digest = hashlib.sha256(canonical_paths.encode("utf-8")).hexdigest()
    task_id = "0123456789abcdef0123456789abcdef"
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps({
            "sender": {"login": "nonkun12"},
            "repository": {"full_name": "nonkun12/line-bot"},
            "inputs": {"instruction": instruction, "user_id": "U123"},
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_ACTOR", "nonkun12")
    monkeypatch.setenv("GITHUB_REPOSITORY", "nonkun12/line-bot")
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", task_id)
    monkeypatch.setenv("AUTONOMOUS_ALLOWED_PATHS", canonical_paths)
    monkeypatch.setenv("AUTONOMOUS_EXECUTION_APPROVAL", "APPROVE_EXECUTION")
    monkeypatch.setenv("AUTONOMOUS_APPROVAL_TASK_ID", task_id)
    monkeypatch.setenv("AUTONOMOUS_APPROVAL_INSTRUCTION_SHA256", instruction_digest)
    monkeypatch.setenv("AUTONOMOUS_APPROVAL_ALLOWED_PATHS_SHA256", paths_digest)
    monkeypatch.setenv("AUTONOMOUS_APPROVAL_BASE_SHA", base_sha)

    evidence = guarded_runtime._verify_execution_approval(base_sha, instruction)

    assert evidence["gate"] == "PASS"
    assert evidence["execution_authorized"] is True
    assert evidence["reason_code"] == "authenticated_workflow_dispatch_approval"
    assert evidence["task_id"] == task_id
    assert evidence["instruction_sha256"] == instruction_digest
    assert evidence["allowed_paths_sha256"] == paths_digest


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AUTONOMOUS_EXECUTION_APPROVAL", "DENY"),
        ("AUTONOMOUS_APPROVAL_TASK_ID", "different-task"),
        ("AUTONOMOUS_APPROVAL_INSTRUCTION_SHA256", "0" * 64),
        ("AUTONOMOUS_APPROVAL_ALLOWED_PATHS_SHA256", "0" * 64),
        ("AUTONOMOUS_APPROVAL_BASE_SHA", "8" * 40),
    ],
)
def test_execution_approval_rejects_mismatched_workflow_envelope(tmp_path, monkeypatch, name, value):
    instruction = "implement a safe bounded feature"
    base_sha = "7" * 40
    paths = ["tests/test_run_guarded_runtime.py"]
    canonical_paths = json.dumps(paths, ensure_ascii=False, separators=(",", ":"))
    task_id = "abcdef0123456789abcdef0123456789"
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps({
            "sender": {"login": "nonkun12"},
            "repository": {"full_name": "nonkun12/line-bot"},
            "inputs": {"instruction": instruction, "user_id": "U123"},
        }),
        encoding="utf-8",
    )
    values = {
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_EVENT_PATH": str(event_path),
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_ACTOR": "nonkun12",
        "GITHUB_REPOSITORY": "nonkun12/line-bot",
        "AUTONOMOUS_TASK_ID": task_id,
        "AUTONOMOUS_ALLOWED_PATHS": canonical_paths,
        "AUTONOMOUS_EXECUTION_APPROVAL": "APPROVE_EXECUTION",
        "AUTONOMOUS_APPROVAL_TASK_ID": task_id,
        "AUTONOMOUS_APPROVAL_INSTRUCTION_SHA256": hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
        "AUTONOMOUS_APPROVAL_ALLOWED_PATHS_SHA256": hashlib.sha256(canonical_paths.encode("utf-8")).hexdigest(),
        "AUTONOMOUS_APPROVAL_BASE_SHA": base_sha,
    }
    values[name] = value
    for key, item in values.items():
        monkeypatch.setenv(key, item)

    evidence = guarded_runtime._verify_execution_approval(base_sha, instruction)

    assert evidence["gate"] == "BLOCKED"
    assert evidence["execution_authorized"] is False


def test_explicit_denial_cannot_fall_back_to_workflow_prepared_approval(tmp_path, monkeypatch):
    instruction = "implement a safe bounded feature"
    base_sha = "6" * 40
    paths = ["tests/test_run_guarded_runtime.py"]
    canonical_paths = json.dumps(paths, ensure_ascii=False, separators=(",", ":"))
    task_id = "fedcba9876543210fedcba9876543210"
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps({
            "sender": {"login": "nonkun12"},
            "repository": {"full_name": "nonkun12/line-bot"},
            "inputs": {
                "instruction": instruction,
                "user_id": "U123",
                "execution_approval": "DENY",
                "approval_task_id": task_id,
                "approval_instruction_sha256": hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
                "approval_base_sha": base_sha,
                "approval_allowed_paths_sha256": hashlib.sha256(canonical_paths.encode("utf-8")).hexdigest(),
            },
        }),
        encoding="utf-8",
    )
    values = {
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_EVENT_PATH": str(event_path),
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_ACTOR": "nonkun12",
        "GITHUB_REPOSITORY": "nonkun12/line-bot",
        "AUTONOMOUS_TASK_ID": task_id,
        "AUTONOMOUS_ALLOWED_PATHS": canonical_paths,
        "AUTONOMOUS_EXECUTION_APPROVAL": "APPROVE_EXECUTION",
        "AUTONOMOUS_APPROVAL_TASK_ID": task_id,
        "AUTONOMOUS_APPROVAL_INSTRUCTION_SHA256": hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
        "AUTONOMOUS_APPROVAL_ALLOWED_PATHS_SHA256": hashlib.sha256(canonical_paths.encode("utf-8")).hexdigest(),
        "AUTONOMOUS_APPROVAL_BASE_SHA": base_sha,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    evidence = guarded_runtime._verify_execution_approval(base_sha, instruction)

    assert evidence["gate"] == "BLOCKED"
    assert evidence["execution_authorized"] is False


def _configure_catalog_schedule(monkeypatch, *, approved=True, instruction="catalog task instruction", paths=None):
    import json

    catalog_paths = paths if paths is not None else ["tests/test_catalog_task.py"]
    catalog = {
        "tasks": [{
            "id": "catalog-task-1",
            "instruction": instruction,
            "allowed_paths": catalog_paths,
            "execution_approved": approved,
        }]
    }
    monkeypatch.setattr(
        guarded_runtime,
        "_git",
        lambda *args: json.dumps(catalog) if args == ("show", "a" * 40 + ":.github/autonomous-loop-task-catalog.json") else "",
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setenv("GITHUB_REPOSITORY", "nonkun12/line-bot")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_ACTOR", "nonkun12")
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "catalog-task-1")
    monkeypatch.setenv("AUTONOMOUS_ALLOWED_PATHS", json.dumps(catalog_paths))


def test_schedule_execution_approval_requires_exact_reviewed_catalog(monkeypatch):
    _configure_catalog_schedule(monkeypatch)
    evidence = guarded_runtime._verify_execution_approval("a" * 40, "catalog task instruction")
    assert evidence["gate"] == "PASS"
    assert evidence["execution_authorized"] is True
    assert evidence["scope"] == "catalog_preapproved_execution"
    assert evidence["reason_code"] == "reviewed_catalog_preapproval"
    assert evidence["catalog_sha"] == "a" * 40


def test_schedule_execution_approval_rejects_unapproved_catalog_task(monkeypatch):
    _configure_catalog_schedule(monkeypatch, approved=False)
    evidence = guarded_runtime._verify_execution_approval("a" * 40, "catalog task instruction")
    assert evidence["gate"] == "BLOCKED"
    assert evidence["execution_authorized"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("instruction", "different instruction"),
        ("paths", ["tests/other.py"]),
    ],
)
def test_schedule_execution_approval_rejects_catalog_definition_mismatch(monkeypatch, field, value):
    import json

    _configure_catalog_schedule(monkeypatch)
    if field == "instruction":
        _configure_catalog_schedule(monkeypatch, instruction=value)
    else:
        monkeypatch.setenv("AUTONOMOUS_ALLOWED_PATHS", json.dumps(value))
    evidence = guarded_runtime._verify_execution_approval("a" * 40, "catalog task instruction")
    assert evidence["gate"] == "BLOCKED"
    assert evidence["execution_authorized"] is False


def test_schedule_execution_approval_rejects_wrong_actor_and_branch(monkeypatch):
    _configure_catalog_schedule(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTOR", "someone-else")
    evidence = guarded_runtime._verify_execution_approval("a" * 40, "catalog task instruction")
    assert evidence["gate"] == "BLOCKED"
    monkeypatch.setenv("GITHUB_ACTOR", "nonkun12")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/unreviewed")
    evidence = guarded_runtime._verify_execution_approval("a" * 40, "catalog task instruction")
    assert evidence["gate"] == "BLOCKED"


def test_run_local_policy_catalog_rejects_catalog_digest_mismatch(monkeypatch, tmp_path):
    from scripts.autonomous_task_target_allowlist import TARGETS

    task_id = "review-coverage-gap-0123456789"
    test_path = TARGETS[0][1]
    base_sha = "f" * 40
    instruction = "Append one deterministic pytest test."
    report_path = tmp_path / "policy-report.json"
    catalog_path = tmp_path / "policy-catalog.json"
    report_path.write_text(json.dumps({
        "status": "POLICY_ADMITTED",
        "admitted_task_id": task_id,
        "admitted_allowed_path": test_path,
        "base_sha": base_sha,
    }), encoding="utf-8")
    catalog_path.write_text(json.dumps({"tasks": [{
        "id": task_id,
        "instruction": instruction,
        "allowed_paths": [test_path],
        "execution_approved": True,
    }]}), encoding="utf-8")
    _bind_policy_catalog_digest(report_path, catalog_path)
    catalog_path.write_text(json.dumps({"tasks": []}), encoding="utf-8")

    monkeypatch.setattr(guarded_runtime, "POLICY_ADMISSION_REPORT_PATH", report_path)
    monkeypatch.setattr(guarded_runtime, "POLICY_ADMISSION_CATALOG_PATH", catalog_path)
    monkeypatch.setenv("AUTONOMOUS_TEST_ADMISSION_POLICY", "true")
    monkeypatch.setenv("AUTONOMOUS_LOOP_TASK_CATALOG", str(catalog_path))
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", task_id)
    monkeypatch.setenv("AUTONOMOUS_ALLOWED_PATHS", json.dumps([test_path]))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setenv("GITHUB_REPOSITORY", "nonkun12/line-bot")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_ACTOR", "nonkun12")

    result = guarded_runtime._verify_catalog_execution_approval(base_sha, instruction)

    assert result["gate"] == "BLOCKED"
    assert result["execution_authorized"] is False


@pytest.mark.parametrize(
    "exit_code,gate_name,reason_code",
    [(81, "execution_approval", "approval_missing"),
     (82, "emergency_stop", "emergency_stop_active")],
)
def test_blocked_summary_contains_explicit_no_authority_gate_evidence(
    monkeypatch, tmp_path, exit_code, gate_name, reason_code
):
    monkeypatch.setattr(guarded_runtime, "_git", lambda *args: "a" * 40)
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "task-gate")
    monkeypatch.setenv("AUTONOMOUS_RUN_NONCE", "b" * 32)
    rea = {
        "gate": "BLOCKED", "reason_code": "rea_denied",
        "execution_authorized": False, "patch_authorized": False,
        "hold_clear_authorized": False, "merge_deploy_authorized": False,
    }
    approval = {
        "gate": "BLOCKED", "reason_code": reason_code,
        "execution_authorized": False, "patch_authorized": False,
        "hold_clear_authorized": False, "merge_deploy_authorized": False,
    }
    summary = tmp_path / "summary.json"
    guarded_runtime._write_summary(
        "BLOCKED", exit_code, "a" * 40, summary, rea, approval
    )
    payload = json.loads(summary.read_text(encoding="utf-8"))
    assert payload["status"] == "BLOCKED"
    assert payload["failure_reason"] == f"guarded_runtime_gate:{gate_name}:{reason_code}"
    assert payload["gate_evidence"]["gate"] == "BLOCKED"
    assert payload["gate_evidence"]["gate_name"] == gate_name
    assert payload["gate_evidence"]["exit_code"] == exit_code
    assert all(payload["gate_evidence"][key] is False for key in (
        "execution_authorized", "patch_authorized", "hold_clear_authorized", "merge_deploy_authorized"
    ))
