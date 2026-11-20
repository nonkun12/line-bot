import json

import pytest

from scripts.autonomous_task_issue_drafts import build_issue_drafts, main


def _report():
    return {
        "status": "REVIEW_REQUIRED",
        "candidate_count": 1,
        "candidates": [{
            "id": "review-coverage-gap-0123456789",
            "target_test": "tests/test_agent_runtime.py",
            "evidence": "core/agent_runtime.py:12",
            "source_function": "AgentRuntime.handle",
            "fingerprint": "a" * 64,
            "status": "REVIEW_REQUIRED",
            "instruction": "untrusted text is ignored",
        }],
        "safety": {"read_only": True, "requires_human_review": True, "candidates_executable": False},
    }


def test_builds_review_only_test_task_issue_with_bounded_spec():
    draft = build_issue_drafts(_report(), [])[0]
    assert draft["task_id"] == "review-coverage-gap-0123456789"
    assert "人手レビュー後に限り" in draft["body"]
    assert "tests/test_agent_runtime.py" in draft["body"]
    assert "untrusted text is ignored" not in draft["body"]
    assert "Queue admission: not authorized" in draft["body"]
    assert "<!-- autonomous-task-spec -->" in draft["body"]
    spec = json.loads(draft["body"].split("<!-- autonomous-task-spec -->")[1].strip().split("<!-- autonomous-task-spec -->")[0])
    assert spec["allowed_paths"] == ["tests/test_agent_runtime.py"]


def test_deduplicates_existing_issue_by_task_id():
    body = "<!-- autonomous-task-spec -->\n" + json.dumps({"id": "review-coverage-gap-0123456789"}) + "\n<!-- autonomous-task-spec -->"
    assert build_issue_drafts(_report(), [{"body": body}]) == []


def test_no_safe_candidate_returns_empty_list():
    report = {"status": "NO_SAFE_CANDIDATE", "candidate_count": 0, "candidates": []}
    assert build_issue_drafts(report, []) == []


@pytest.mark.parametrize("mutate", [
    lambda r: r["candidates"][0].update(target_test="../unsafe.py"),
    lambda r: r["candidates"][0].update(fingerprint="bad"),
    lambda r: r["safety"].update(candidates_executable=True),
    lambda r: r.update(candidate_count=2),
])
def test_invalid_evidence_fails_closed(mutate):
    report = _report()
    mutate(report)
    with pytest.raises(ValueError):
        build_issue_drafts(report, [])


def test_main_writes_drafts(tmp_path):
    report, issues, output = tmp_path / "report.json", tmp_path / "issues.json", tmp_path / "drafts.json"
    report.write_text(json.dumps(_report()), encoding="utf-8")
    issues.write_text("[]", encoding="utf-8")
    assert main(["--report", str(report), "--issues", str(issues), "--output", str(output)]) == 0
    assert len(json.loads(output.read_text(encoding="utf-8"))) == 1

def test_observation_workflow_does_not_create_candidate_issues():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "distributed-autonomous-observation.yml").read_text(encoding="utf-8")
    assert "gh issue create" not in workflow
    assert "gh pr create" not in workflow
    assert "READ_ONLY" in workflow
    assert "actions/upload-artifact" in workflow


def test_observation_workflow_reads_issue_and_pr_signals_without_writes():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "distributed-autonomous-observation.yml").read_text(encoding="utf-8")
    assert 'repos/${REPOSITORY}/issues?state=all&per_page=100' in workflow
    assert 'repos/${REPOSITORY}/pulls?state=open&per_page=100' in workflow
    assert "issues: read" in workflow
    assert "pull-requests: read" in workflow
    assert "git push" not in workflow


def _open_review_issue(task_id="review-coverage-gap-0123456789", approved=False):
    body = "<!-- autonomous-task-spec -->\n" + json.dumps({"id": task_id}) + "\n<!-- autonomous-task-spec -->"
    labels = [{"name": "autonomous-task-candidate"}]
    if approved:
        labels.append({"name": "autonomous-task-execution-approved"})
    return {"state": "open", "labels": labels, "body": body}


def test_stops_candidate_generation_when_four_review_issues_are_open():
    issues = [_open_review_issue(f"review-coverage-gap-{i:010d}") for i in range(4)]
    assert build_issue_drafts(_report(), issues) == []


def test_caps_new_candidates_to_remaining_review_backlog_capacity():
    report = _report()
    report["candidate_count"] = 1
    issues = [_open_review_issue(f"review-coverage-gap-{i:010d}") for i in range(3)]
    drafts = build_issue_drafts(report, issues)
    assert len(drafts) == 1


def test_closed_or_execution_approved_issues_do_not_consume_review_capacity():
    closed = _open_review_issue("review-coverage-gap-2222222222")
    closed["state"] = "closed"
    approved = _open_review_issue("review-coverage-gap-1111111111", approved=True)
    assert build_issue_drafts(_report(), [closed, approved])


def test_open_pr_closing_candidate_issue_does_not_consume_review_capacity():
    issues = [_open_review_issue(f"review-coverage-gap-{i:010d}") for i in range(4)]
    for number, issue in enumerate(issues, start=1155):
        issue["number"] = number
    pull_requests = [{
        "number": 1300,
        "state": "open",
        "merged_at": None,
        "body": "Fixes #1155; Closes #1156; Resolves #1157",
    }]
    drafts = build_issue_drafts(_report(), issues, pull_requests)
    assert len(drafts) == 1


def test_closed_pr_does_not_release_review_backlog_capacity():
    issues = [_open_review_issue(f"review-coverage-gap-{i:010d}") for i in range(4)]
    for number, issue in enumerate(issues, start=1155):
        issue["number"] = number
    pull_requests = [{
        "number": 1300,
        "state": "closed",
        "merged_at": None,
        "body": "Fixes #1155",
    }]
    assert build_issue_drafts(_report(), issues, pull_requests) == []


def test_non_closing_pr_reference_does_not_release_review_backlog_capacity():
    issues = [_open_review_issue(f"review-coverage-gap-{i:010d}") for i in range(4)]
    for number, issue in enumerate(issues, start=1155):
        issue["number"] = number
    pull_requests = [{
        "number": 1300,
        "state": "open",
        "merged_at": None,
        "body": "Related to #1155",
    }]
    assert build_issue_drafts(_report(), issues, pull_requests) == []


def test_main_reports_review_backlog_limit_and_deduplication(tmp_path, capsys):
    report = _report()
    report_path = tmp_path / "report.json"
    issues_path = tmp_path / "issues.json"
    output_path = tmp_path / "drafts.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    issues = [_open_review_issue(f"review-coverage-gap-{i:010d}") for i in range(4)]
    issues_path.write_text(json.dumps(issues), encoding="utf-8")

    assert main([
        "--report", str(report_path),
        "--issues", str(issues_path),
        "--output", str(output_path),
    ]) == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "REVIEW_BACKLOG_FULL"
    assert summary["candidate_count"] == 1
    assert summary["open_review_issue_count"] == 4
    assert summary["review_issue_limit"] == 4
    assert summary["remaining_capacity"] == 0
    assert summary["draft_count"] == 0
    assert summary["execution_approval_granted"] is False


def test_observation_artifact_contains_read_only_approval_preflight():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "distributed-autonomous-observation.yml").read_text(encoding="utf-8")
    assert "approval_candidates" in workflow
    assert "instruction_sha256" in workflow
    assert "allowed_paths_sha256" in workflow
    assert "safety_boundary" in workflow


def test_review_only_issue_with_misapplied_execution_label_still_consumes_backlog_capacity():
    # An approval label alone cannot erase an explicitly unapproved review issue.
    contradictory = _open_review_issue("review-coverage-gap-9999999999", approved=True)
    contradictory["number"] = 1155
    contradictory["body"] = (
        "このIssueは候補の記録です。実行承認ではありません。\n"
        "Queue admission: not authorized\n"
        + contradictory["body"]
    )
    ordinary = [
        _open_review_issue(f"review-coverage-gap-{i:010d}")
        for i in range(3)
    ]

    # Four open review issues fill the cap; no additional draft may be produced.
    assert build_issue_drafts(_report(), [*ordinary, contradictory]) == []
