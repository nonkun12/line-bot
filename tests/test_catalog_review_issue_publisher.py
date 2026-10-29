import json

import pytest

from scripts.catalog_review_issue_publisher import build_issue_payloads, main


def _report():
    return {
        "status": "REVIEW_REQUIRED",
        "candidate_count": 1,
        "safety": {
            "read_only": True,
            "requires_human_review": True,
            "candidates_executable": False,
        },
        "candidates": [{
            "id": "review-coverage-gap-0123456789",
            "fingerprint": "a" * 64,
            "target_test": "tests/test_agent_runtime.py",
            "evidence": "core/agent_runtime.py:12",
            "source_function": "AgentRuntime.handle",
            "instruction": "Review and add one bounded regression test after human review.",
            "status": "REVIEW_REQUIRED",
        }],
    }


def test_builds_review_only_issue_with_valid_task_spec():
    payloads = build_issue_payloads(_report(), [])
    assert len(payloads) == 1
    row = payloads[0]
    assert row["labels"] == ["autonomous-task-candidate"]
    assert row["execution_authorized"] is False
    assert "<!-- autonomous-task-spec -->" in row["body"]
    spec = json.loads(row["body"].split("<!-- autonomous-task-spec -->")[1].strip().split("<!-- autonomous-task-spec -->")[0])
    assert spec == {
        "id": "review-coverage-gap-0123456789",
        "instruction": "Review and add one bounded regression test after human review.",
        "allowed_paths": ["tests/test_agent_runtime.py"],
    }


def test_deduplicates_open_or_closed_issue_using_stable_marker():
    report = _report()
    existing = [{"state": "closed", "body": "<!-- catalog-exhaustion-candidate:review-coverage-gap-0123456789 -->"}]
    assert build_issue_payloads(report, existing) == []


def test_non_review_report_creates_no_issue():
    report = {"status": "NO_SAFE_CANDIDATE", "candidate_count": 0, "candidates": [], "safety": {"candidates_executable": False}}
    assert build_issue_payloads(report, []) == []


@pytest.mark.parametrize("mutate", [
    lambda r: r["candidates"][0].update(target_test="../unsafe.py"),
    lambda r: r["candidates"][0].update(fingerprint="bad"),
    lambda r: r["safety"].update(candidates_executable=True),
    lambda r: r.update(candidate_count=2),
    lambda r: r["candidates"][0].update(id="existing-task"),
])
def test_rejects_unsafe_or_malformed_candidate(mutate):
    report = _report()
    mutate(report)
    with pytest.raises(ValueError):
        build_issue_payloads(report, [])


def test_main_writes_bounded_payloads(tmp_path):
    report = tmp_path / "report.json"
    issues = tmp_path / "issues.json"
    output = tmp_path / "payloads.json"
    report.write_text(json.dumps(_report()), encoding="utf-8")
    issues.write_text("[]", encoding="utf-8")
    assert main(["--report", str(report), "--existing-issues", str(issues), "--output", str(output)]) == 0
    assert len(json.loads(output.read_text(encoding="utf-8"))) == 1
