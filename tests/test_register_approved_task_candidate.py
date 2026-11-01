import json

import pytest

from scripts.register_approved_task_candidate import register_approved_candidate, main


SOURCE = "core/agent_runtime.py"
TEST = "tests/test_agent_runtime.py"
TASK_ID = "review-coverage-gap-0123456789"
TICK = chr(96)


def issue(labels=("autonomous-task-candidate", "autonomous-task-approved"), task_id=TASK_ID, path=TEST):
    spec = {
        "id": task_id,
        "instruction": "Add one focused regression test after human review.",
        "allowed_paths": [path],
    }
    body = (
        "## Review-only task candidate\n"
        "- Source evidence: " + TICK + "core/agent_runtime.py:12" + TICK + "\n"
        "- Analyzer fingerprint: " + TICK + "a" * 64 + TICK + "\n"
        "- Queue admission: not authorized\n"
        "<!-- autonomous-task-spec -->\n"
        + json.dumps(spec)
        + "\n<!-- autonomous-task-spec -->"
    )
    return {
        "number": 123,
        "state": "open",
        "labels": [{"name": name} for name in labels],
        "body": body,
    }


def catalog(tasks=None):
    return {"version": 1, "tasks": list(tasks or [])}


def state(completed=None, tasks=None):
    return {
        "version": 1,
        "completed": list(completed or []),
        "recovery_ai": {"schema_version": 1, "tasks": dict(tasks or {}), "checkpoint": None},
    }


def test_registers_explicitly_approved_analyzer_candidate_for_pr_review():
    result, changed = register_approved_candidate(issue(), catalog(), state())
    assert changed is True
    assert result["status"] == "REGISTERED_FOR_REVIEW"
    assert result["catalog_entry"]["id"] == TASK_ID
    assert result["catalog_entry"]["allowed_paths"] == [TEST]


def test_candidate_label_without_explicit_approval_cannot_register():
    with pytest.raises(ValueError, match="explicit human-approval"):
        register_approved_candidate(
            issue(labels=("autonomous-task-candidate",)),
            catalog(),
            state(),
        )


def test_non_allowlisted_path_cannot_register():
    with pytest.raises(ValueError, match="not in the analyzer allowlist"):
        register_approved_candidate(issue(path="../secrets.env"), catalog(), state())


def test_source_evidence_must_match_the_allowlisted_test_target():
    bad = issue()
    bad["body"] = bad["body"].replace("core/agent_runtime.py:12", "core/recovery_ai.py:12")
    with pytest.raises(ValueError, match="source evidence"):
        register_approved_candidate(bad, catalog(), state())


def test_completed_or_held_candidates_cannot_register():
    with pytest.raises(ValueError, match="already completed"):
        register_approved_candidate(issue(), catalog(), state(completed=[TASK_ID]))
    with pytest.raises(ValueError, match="held"):
        register_approved_candidate(
            issue(),
            catalog(),
            state(tasks={TASK_ID: {"held": True}}),
        )


def test_existing_identical_catalog_entry_is_idempotent():
    spec = {
        "id": TASK_ID,
        "instruction": "Add one focused regression test after human review.",
        "allowed_paths": [TEST],
    }
    result, changed = register_approved_candidate(issue(), catalog([spec]), state())
    assert changed is False
    assert result["status"] == "ALREADY_REGISTERED"


def test_conflicting_catalog_definition_fails_closed():
    existing = {
        "id": TASK_ID,
        "instruction": "different task",
        "allowed_paths": [TEST],
    }
    with pytest.raises(ValueError, match="conflicts"):
        register_approved_candidate(issue(), catalog([existing]), state())


def test_cli_writes_catalog_only_after_explicit_approval(tmp_path):
    issue_path = tmp_path / "issue.json"
    catalog_path = tmp_path / "catalog.json"
    state_path = tmp_path / "state.json"
    issue_path.write_text(json.dumps(issue()), encoding="utf-8")
    catalog_path.write_text(json.dumps(catalog()), encoding="utf-8")
    state_path.write_text(json.dumps(state()), encoding="utf-8")
    assert main([
        "--issue", str(issue_path),
        "--catalog", str(catalog_path),
        "--state", str(state_path),
    ]) == 0
    updated = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert updated["tasks"][-1]["id"] == TASK_ID


def test_catalog_candidate_workflow_only_creates_draft_registration_pr():
    from pathlib import Path

    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "register-approved-autonomous-task.yml"
    ).read_text(encoding="utf-8")
    assert "types: [labeled]" in workflow
    assert "github.event.label.name == 'autonomous-task-approved'" in workflow
    assert "autonomous-task-candidate" in workflow
    assert "scripts/register_approved_task_candidate.py" in workflow
    assert "gh pr create --draft" in workflow
    assert "pull-requests: write" in workflow
    assert "contents: write" in workflow
    assert "gh pr merge" not in workflow
    assert 'branch="automation/register-approved-task-${ISSUE_NUMBER}"' in workflow
    assert '--head "${branch}"' in workflow
    assert "git push origin \"${branch}\"" in workflow
