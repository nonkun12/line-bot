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

def test_distributed_workflow_creates_only_review_candidate_issues():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    start = workflow.index("- name: Create bounded review-only task issues from analyzer findings")
    end = workflow.index("- name: Run one bounded autonomous task", start)
    step = workflow[start:end]
    assert "scripts.autonomous_task_issue_drafts" in step
    assert "gh issue create" in step
    assert "--label autonomous-task-candidate" in step
    assert "autonomous-task-approved" not in step
    assert "no execution approval was granted" in step



def test_distributed_workflow_paginates_all_issues_for_deduplication():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    start = workflow.index("- name: Create bounded review-only task issues from analyzer findings")
    end = workflow.index("- name: Run one bounded autonomous task", start)
    step = workflow[start:end]
    assert "gh api --paginate" in step
    assert "state=all&per_page=100" in step
    assert "jq -s '.'" in step
