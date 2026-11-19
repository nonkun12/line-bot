import json

import pytest

from scripts.autonomous_task_review_digest import build_review_digest, main


MARKER = "<!-- autonomous-task-spec -->"


def _issue(number=1, title="Review-only test task: main", approved=False, source="scripts/example.py:12", function="main", created="2026-01-01T00:00:00Z"):
    labels = [{"name": "autonomous-task-candidate"}]
    if approved:
        labels.extend([{"name": "autonomous-task-execution-approved"}, {"name": "autonomous-task-catalog-approved"}])
    body = (
        f"- Source evidence: `{source}`\n"
        f"- Source function: `{function}`\n"
        f"{MARKER}\n" + json.dumps({"id": f"review-task-{number}"}) + f"\n{MARKER}"
    )
    return {"number": number, "title": title, "state": "open", "created_at": created, "updated_at": created, "labels": labels, "body": body}


def test_digest_counts_separate_approval_states_and_flags_duplicate_titles():
    report = build_review_digest([
        _issue(2, approved=True, source="scripts/b.py:4", function="main"),
        _issue(1, source="scripts/a.py:3", function="main"),
    ])
    assert "Open review candidates: **2**" in report
    assert "Awaiting execution approval: **1**" in report
    assert "Execution-approved: **1**" in report
    assert "Catalog-approved label present: **1**" in report
    assert "⚠ duplicate title" in report
    assert report.index("[#1]") < report.index("[#2]")


def test_ignores_closed_non_candidate_and_invalid_spec_issues():
    closed = _issue(3)
    closed["state"] = "closed"
    non_candidate = _issue(4)
    non_candidate["labels"] = []
    invalid = _issue(5)
    invalid["body"] = "no task spec"
    report = build_review_digest([closed, non_candidate, invalid])
    assert "Open review candidates: **0**" in report


def test_digest_is_explicitly_read_only_and_does_not_claim_queue_eligibility():
    report = build_review_digest([_issue()])
    assert "does not grant approval" in report
    assert "does not inspect the runtime queue" in report
    assert "eligible, or executable" in report


def test_rejects_invalid_input():
    with pytest.raises(ValueError):
        build_review_digest({"not": "a list"})


def test_main_writes_digest(tmp_path):
    issues = tmp_path / "issues.json"
    output = tmp_path / "digest.md"
    issues.write_text(json.dumps([_issue()]), encoding="utf-8")
    assert main(["--issues", str(issues), "--output", str(output)]) == 0
    assert "Autonomous task review backlog" in output.read_text(encoding="utf-8")
