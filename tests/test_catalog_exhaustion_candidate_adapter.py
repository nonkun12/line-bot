import json

import pytest

from scripts.catalog_exhaustion_candidate_adapter import merge_candidates, main
from scripts.review_candidate_bridge import build_pool


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
            "instruction": "untrusted instruction must not be persisted",
        }],
        "safety": {
            "read_only": True,
            "requires_human_review": True,
            "candidates_executable": False,
        },
    }


def test_merges_catalog_findings_as_review_only_history_candidates():
    rows = merge_candidates([], _report())
    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == "self_improvement"
    assert row["source_id"] == "catalog-exhaustion:review-coverage-gap-0123456789"
    assert row["status"] == "proposed"
    assert "tests/test_agent_runtime.py" in row["rationale"]
    assert "untrusted instruction" not in json.dumps(row)
    assert "execution_authorized" not in row


def test_preserves_history_and_deduplicates_catalog_candidate():
    report = _report()
    row = merge_candidates([], report)[0]
    assert merge_candidates([row], report) == [row]


def test_no_safe_candidate_report_leaves_history_unchanged():
    history = [{"source": "self_improvement", "source_id": "old", "title": "Old", "rationale": "Keep", "status": "proposed"}]
    report = {"status": "NO_SAFE_CANDIDATE", "candidate_count": 0, "candidates": [], "safety": {"candidates_executable": False}}
    assert merge_candidates(history, report) == history


@pytest.mark.parametrize("mutate", [
    lambda r: r["candidates"][0].update(target_test="../unsafe.py"),
    lambda r: r["candidates"][0].update(fingerprint="bad"),
    lambda r: r["safety"].update(candidates_executable=True),
    lambda r: r.update(candidate_count=2),
])
def test_invalid_analyzer_evidence_fails_closed(mutate):
    report = _report()
    mutate(report)
    with pytest.raises(ValueError):
        merge_candidates([], report)


def test_main_combines_files(tmp_path):
    history = tmp_path / "history.json"
    report = tmp_path / "report.json"
    output = tmp_path / "output.json"
    history.write_text("[]", encoding="utf-8")
    report.write_text(json.dumps(_report()), encoding="utf-8")
    assert main(["--history", str(history), "--catalog-report", str(report), "--output", str(output)]) == 0
    assert len(json.loads(output.read_text(encoding="utf-8"))) == 1


def test_catalog_exhaustion_findings_reach_review_only_candidate_pool(tmp_path):
    """Exercise the exact adapter -> review-pool handoff used by the workflow."""
    input_path = tmp_path / "review-candidate-input.json"
    store_path = tmp_path / "candidates.jsonl"
    summary_path = tmp_path / "summary.md"

    merged = merge_candidates([], _report())
    input_path.write_text(json.dumps(merged), encoding="utf-8")

    first = build_pool(input_path, store_path, summary_path)
    stored = [json.loads(line) for line in store_path.read_text(encoding="utf-8").splitlines()]

    assert first == {"stored": 1, "added": 1, "rejected": 0}
    assert len(stored) == 1
    assert stored[0]["source"] == "self_improvement"
    assert stored[0]["source_id"] == "catalog-exhaustion:review-coverage-gap-0123456789"
    assert stored[0]["execution_authorized"] is False
    summary = summary_path.read_text(encoding="utf-8")
    assert "Stored candidates: 1" in summary
    assert "Execution authorization: **none**" in summary
    assert "Queue / issue / PR creation: **not performed**" in summary

    # Re-running the handoff must remain idempotent and must not duplicate rows.
    second = build_pool(input_path, store_path, summary_path)
    assert second == {"stored": 1, "added": 0, "rejected": 0}
    assert len(store_path.read_text(encoding="utf-8").splitlines()) == 1


def test_distributed_workflow_wires_analyzer_adapter_before_review_pool(tmp_path):
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "distributed-autonomous-loop.yml").read_text(encoding="utf-8")
    start = workflow.index("- name: Build review-only self-improvement candidate pool")
    end = workflow.index("- name: Upload review-only self-improvement candidates", start)
    step = workflow[start:end]

    adapter = step.index("scripts/catalog_exhaustion_candidate_adapter.py")
    bridge = step.index("scripts/review_candidate_bridge.py")
    assert adapter < bridge
    assert "--history /tmp/self-improvement-review-candidates.json" in step
    assert "--catalog-report /tmp/catalog-exhaustion-report.json" in step
    assert "--output /tmp/review-candidate-input.json" in step
    assert "--input /tmp/review-candidate-input.json" in step
    assert "--store artifacts/self-improvement-candidates/candidates.jsonl" in step
    assert "--summary artifacts/self-improvement-candidates/summary.md" in step
    assert "if [ -s /tmp/catalog-exhaustion-report.json ]; then" in step
    assert "cp /tmp/self-improvement-review-candidates.json /tmp/review-candidate-input.json" in step
