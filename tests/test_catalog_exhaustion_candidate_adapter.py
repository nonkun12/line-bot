import json

import pytest

from scripts.catalog_exhaustion_candidate_adapter import merge_candidates, main


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


def test_analyzer_candidates_reach_persisted_review_only_pool(tmp_path):
    from scripts.self_improvement_candidate_adapter import candidates_from_history
    from scripts.review_candidate_bridge import build_pool

    report = _report()
    base = report["candidates"][0]
    targets = [
        ("review-coverage-gap-0123456789", "core/agent_runtime.py", "tests/test_agent_runtime.py", "AgentRuntime.handle", 12),
        ("review-coverage-gap-1123456789", "core/control_tower_orchestrator.py", "tests/test_control_tower_orchestrator.py", "ControlTower.decide", 24),
        ("review-coverage-gap-2123456789", "core/recovery_ai.py", "tests/test_recovery_ai.py", "RecoveryAI.review", 36),
    ]
    report["candidates"] = [
        {
            **base,
            "id": task_id,
            "target_test": target_test,
            "evidence": f"{target_code}:{line}",
            "source_function": source_function,
            "fingerprint": str(index) * 64,
        }
        for index, (task_id, target_code, target_test, source_function, line)
        in enumerate(targets, start=1)
    ]
    report["candidate_count"] = len(report["candidates"])

    history = candidates_from_history([])
    merged = merge_candidates(history, report)
    input_path = tmp_path / "review-candidate-input.json"
    store_path = tmp_path / "candidates.jsonl"
    summary_path = tmp_path / "summary.md"
    input_path.write_text(json.dumps(merged), encoding="utf-8")

    result = build_pool(input_path, store_path, summary_path)
    stored = [
        json.loads(line)
        for line in store_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert result == {"stored": 3, "added": 3, "rejected": 0}
    assert {row["source_id"] for row in stored} == {
        "catalog-exhaustion:" + item[0] for item in targets
    }
    assert all(row["status"] == "proposed" for row in stored)
    assert all(row["execution_authorized"] is False for row in stored)
    assert "Stored candidates: 3" in summary_path.read_text(encoding="utf-8")
