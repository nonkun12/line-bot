from __future__ import annotations

from scripts.loop_self_heal_dispatch import maybe_run_repair


def _recovery():
    return {
        "recorded": True,
        "decision": {"action": "REPAIR_ONCE", "reason": "bounded_repair_attempt"},
    }


def _catalog(**changes):
    task = {
        "id": "task-1",
        "execution_approved": True,
        "repair_approved": True,
    }
    task.update(changes)
    return [task]


def test_dispatch_skips_when_recovery_ai_did_not_request_repair():
    assert maybe_run_repair(
        "task-1", {"recorded": True, "decision": {"action": "HOLD"}},
        _catalog(), "/tmp/recovery.json", env={"GITHUB_TOKEN": "token"},
    ) is None


def test_dispatch_requires_separate_catalog_repair_approval():
    result = maybe_run_repair(
        "task-1", _recovery(), _catalog(repair_approved=False),
        "/tmp/recovery.json", env={"GITHUB_TOKEN": "token"},
    )
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "catalog_repair_approval_missing"


def test_dispatch_never_attempts_local_model_from_hosted_runner():
    called = []
    result = maybe_run_repair(
        "task-1", _recovery(), _catalog(), "/tmp/recovery.json",
        env={"GITHUB_ACTIONS": "true", "GITHUB_TOKEN": "token"},
        repair_runner=lambda *_args: called.append(True),
    )
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "local_model_not_available_in_hosted_runner"
    assert called == []


def test_dispatch_invokes_one_repair_only_after_all_gates_pass():
    calls = []
    result = maybe_run_repair(
        "task-1", _recovery(), _catalog(), "/tmp/recovery.json",
        env={"GITHUB_TOKEN": "free-github-token"},
        repair_runner=lambda *args: calls.append(args) or {
            "status": "REPAIR_VERIFIED", "hold_clear_authorized": True,
            "resume_authorized": True, "merge_deploy_authorized": True,
        },
    )
    assert result["status"] == "REPAIR_VERIFIED"
    assert calls == [("task-1", "/tmp/recovery.json", "free-github-token")]
    assert result["hold_clear_authorized"] is False
    assert result["resume_authorized"] is False
    assert result["merge_deploy_authorized"] is False



def test_dispatch_allows_only_preapproved_catalog_patch_on_hosted_runner():
    calls = []
    task = _catalog()[0]
    task["repair_patch"] = "--- a/tests/test.py\n+++ b/tests/test.py\n@@ -1 +1 @@\n-a\n+b\n"
    task["repair_patch_sha256"] = "a" * 64
    result = maybe_run_repair(
        "task-1", _recovery(), [task], "/tmp/recovery.json",
        env={"GITHUB_ACTIONS": "true", "GITHUB_TOKEN": "token"},
        repair_runner=lambda *args: calls.append(args) or {"status": "REPAIR_VERIFIED"},
    )
    assert result["status"] == "REPAIR_VERIFIED"
    assert calls == [("task-1", "/tmp/recovery.json", "token")]
