from __future__ import annotations

from scripts import loop_repair_executor as executor


BASE = "a" * 40
TASK = "unit-test-repair"
EVIDENCE = {
    "task_id": TASK,
    "instruction_sha256": "b" * 64,
    "base_sha": BASE,
    "failure_fingerprint": "c" * 64,
    "allowed_paths": ["tests/test_example.py"],
    "catalog_repair_approved": True,
    "execution_approved": True,
    "held": False,
    "working_tree_clean": True,
    "rea_status": "PRE_REPAIR_PASS",
    "failure_category": "test_regression",
    "repair_attempts": 0,
    "current_head_sha": BASE,
}


def _install_git_state(monkeypatch, *, status="", changed="tests/test_example.py", staged="", untracked="", head=BASE):
    values = {
        ("rev-parse", "HEAD"): head,
        ("status", "--porcelain", "--untracked-files=all"): status,
        ("diff", "--name-only"): changed,
        ("diff", "--cached", "--name-only"): staged,
        ("ls-files", "--others", "--exclude-standard"): untracked,
    }
    monkeypatch.setattr(executor, "_git", lambda _root, *args: values[tuple(args)])


def _consume_pass(monkeypatch):
    monkeypatch.setattr(
        executor, "consume_repair_authorization",
        lambda *_args, **_kwargs: {"gate": "PASS", "reason_code": "consumed"},
    )


def _rea_pass(request):
    return {
        "status": "PASS",
        "base_sha": request["base_sha"],
        "evaluated_paths": request["changed_paths"],
        "independent": True,
    }


def test_repair_requires_clean_authorized_base_before_consumption(monkeypatch, tmp_path):
    _install_git_state(monkeypatch, status=" M unrelated.py")
    called = []
    result = executor.execute_one_repair(
        EVIDENCE, token="token", repair_executor=lambda _request: called.append(True) or {"status": "PASS"},
        rea_runner=_rea_pass, repo_root=tmp_path,
    )
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "repository_not_at_clean_authorized_base"
    assert called == []


def test_repair_runs_once_and_requires_independent_post_rea(monkeypatch, tmp_path):
    _install_git_state(monkeypatch)
    _consume_pass(monkeypatch)
    repair_requests = []
    rea_requests = []
    result = executor.execute_one_repair(
        EVIDENCE, token="token",
        repair_executor=lambda request: repair_requests.append(request) or {"status": "PASS"},
        rea_runner=lambda request: rea_requests.append(request) or _rea_pass(request),
        repo_root=tmp_path,
    )
    assert result["status"] == "REPAIR_VERIFIED"
    assert result["repair_attempts"] == 1
    assert len(repair_requests) == 1
    assert repair_requests[0]["provider_policy"] == "provider_free_only"
    assert rea_requests[0]["stage"] == "POST_REPAIR"
    assert result["hold_clear_authorized"] is False
    assert result["resume_authorized"] is False


def test_repair_blocks_changes_outside_allowlist(monkeypatch, tmp_path):
    _install_git_state(monkeypatch, changed="tests/test_example.py\napp.py")
    _consume_pass(monkeypatch)
    result = executor.execute_one_repair(
        EVIDENCE, token="token", repair_executor=lambda _request: {"status": "PASS"},
        rea_runner=_rea_pass, repo_root=tmp_path,
    )
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "repair_changed_paths_outside_allowlist_or_no_change"


def test_repair_blocks_when_post_rea_is_not_independent_pass(monkeypatch, tmp_path):
    _install_git_state(monkeypatch)
    _consume_pass(monkeypatch)
    result = executor.execute_one_repair(
        EVIDENCE, token="token", repair_executor=lambda _request: {"status": "PASS"},
        rea_runner=lambda _request: {"status": "PASS", "independent": False},
        repo_root=tmp_path,
    )
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "post_repair_rea_not_independent_pass"


def test_repair_blocks_when_one_shot_authorization_was_already_consumed(monkeypatch, tmp_path):
    _install_git_state(monkeypatch)
    monkeypatch.setattr(
        executor, "consume_repair_authorization",
        lambda *_args, **_kwargs: {"gate": "BLOCKED", "reason_code": "repair_attempt_already_consumed"},
    )
    called = []
    result = executor.execute_one_repair(
        EVIDENCE, token="token", repair_executor=lambda _request: called.append(True) or {"status": "PASS"},
        rea_runner=_rea_pass, repo_root=tmp_path,
    )
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "repair_attempt_already_consumed"
    assert called == []
