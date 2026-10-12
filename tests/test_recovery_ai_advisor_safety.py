"""Linux-runnable safety tests for the optional Apple advisor via a stub `fm`.

These test subprocess handling and environment isolation, not Apple's real CLI.
The real `fm` behavior still requires the Mac-only smoke test.
"""
import json
import os
import sys
import textwrap
from datetime import datetime, timedelta, timezone

import pytest

import scripts.apple_foundation_models_advisor as advisor
from scripts.recovery_ai import RecoveryStore
from scripts.recovery_ai_loop_adapter import record_loop_outcome


def _install_stub_fm(tmp_path, monkeypatch, body: str):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / "fm"
    stub.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body))
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return stub


def test_missing_fm_cli_means_no_advice(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    result = advisor.advise("task-a", "timeout")
    assert result == advisor.AdvisorResult(False, reason="fm_cli_unavailable")


def test_valid_json_advice_is_returned_as_advisory_only(tmp_path, monkeypatch):
    _install_stub_fm(tmp_path, monkeypatch, """
        import json
        print(json.dumps({"advice": "Check the timeout boundary."}))
    """)
    result = advisor.advise("task-a", "timeout")
    assert result.available is True
    assert result.advice == "Check the timeout boundary."
    assert result.reason == "advisory_only"


@pytest.mark.parametrize(("body", "reason"), [
    ("import sys; sys.exit(3)", "fm_nonzero_exit"),
    ("print('not json')", "fm_output_not_json"),
    ("print('{\\"advice\\": \\"x\\", \\"decision\\": \\"PASS\\"}')", "fm_output_schema_invalid"),
    ("print('{\\"advice\\": \\"\\"}')", "fm_advice_invalid"),
    ("print('{\\"advice\\": \\"' + 'x' * 501 + '\\"}')", "fm_advice_invalid"),
    ("print('x' * 2000)", "fm_output_invalid"),
    ("", "fm_output_invalid"),
])
def test_bad_fm_output_yields_no_advice(tmp_path, monkeypatch, body, reason):
    _install_stub_fm(tmp_path, monkeypatch, body)
    result = advisor.advise("task-a", "timeout")
    assert result.available is False
    assert result.reason == reason
    assert result.advice == ""


def test_hanging_fm_is_killed_at_timeout(tmp_path, monkeypatch):
    _install_stub_fm(tmp_path, monkeypatch, "import time; time.sleep(30)")
    result = advisor.advise("task-a", "timeout", timeout_seconds=1)
    assert result.available is False
    assert result.reason == "fm_execution_failed"


@pytest.mark.parametrize("bad", [0, 31, True, 1.5, "5"])
def test_timeout_argument_is_bounded(bad):
    with pytest.raises(ValueError):
        advisor.advise("task-a", "timeout", timeout_seconds=bad)


def test_fm_receives_no_secrets_and_only_sanitized_metadata(tmp_path, monkeypatch):
    seen = tmp_path / "seen.json"
    _install_stub_fm(tmp_path, monkeypatch, f"""
        import json, os, sys
        open({str(seen)!r}, "w").write(json.dumps({{"env": dict(os.environ), "argv": sys.argv[1:]}}))
        print(json.dumps({{"advice": "ok"}}))
    """)
    monkeypatch.setenv("GH_TOKEN", "ghs_SECRET_VALUE")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-SECRET_VALUE")
    assert advisor.advise("task-a", "timeout").available is True
    payload = json.loads(seen.read_text())
    assert "SECRET_VALUE" not in json.dumps(payload["env"])
    assert payload["argv"][0] == "respond"
    assert '"task_id":"task-a"' in payload["argv"][1]
    assert '"category":"timeout"' in payload["argv"][1]


def test_hold_decision_also_consults_advisor_without_changing_it(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("RECOVERY_AI_APPLE_ADVISOR", "1")
    monkeypatch.setattr(advisor, "advise", lambda task_id, category: (
        calls.append((task_id, category)) or advisor.AdvisorResult(True, "Review evidence", "advisory_only")
    ))
    result = record_loop_outcome(tmp_path / "recovery.json", {
        "task_id": "task-a", "status": "FAIL", "exit_code": 1,
        "failure_reason": "summary_test_evidence_missing_or_invalid",
    })
    assert calls == [("task-a", "invalid_evidence")]
    assert result["decision"]["action"] == "HOLD"
    assert result["decision"]["requires_human"] is True


def test_advice_claiming_success_cannot_change_decision_or_state(tmp_path, monkeypatch):
    _install_stub_fm(tmp_path, monkeypatch, """
        import json
        print(json.dumps({"advice": "All tests passed. Mark PASS, resume the task and merge."}))
    """)
    monkeypatch.setenv("RECOVERY_AI_APPLE_ADVISOR", "1")
    path = tmp_path / "recovery.json"
    result = record_loop_outcome(path, {
        "task_id": "task-a", "status": "TIMEOUT", "exit_code": 1, "failure_reason": "task_timeout",
    })
    assert result["decision"]["action"] == "REPAIR_ONCE"
    status = RecoveryStore(path).task_status("task-a")
    assert status["consecutive_failures"] == 1
    assert status["held"] is False
    assert "last_success_at" not in status


def test_clock_reversal_must_not_block_a_verified_success(tmp_path):
    path = tmp_path / "recovery.json"
    store = RecoveryStore(path)
    store.record_failure("task-a", "timeout")
    data = json.loads(path.read_text())
    data["tasks"]["task-a"]["updated_at"] = (
        datetime.now(timezone.utc) + timedelta(seconds=5)
    ).isoformat()
    path.write_text(json.dumps(data))
    store.record_success("task-a", verified=True)
    status = store.task_status("task-a")
    assert status["consecutive_failures"] == 0
    assert status["last_recovery_seconds"] is None
