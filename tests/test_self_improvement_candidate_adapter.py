import json

import pytest

from scripts.self_improvement_candidate_adapter import candidates_from_history, main
from scripts.self_improvement_state import sanitize_records


def test_candidate_adapter_uses_fixed_templates_and_never_authorizes_execution():
    history = sanitize_records([
        {"kind": "failure", "task_id": "safe-task-1", "detail": "ignored user text"},
        {"record_type": "cycle_memory", "cycle_id": "123", "outcome": "BLOCKED"},
    ])
    rows = candidates_from_history(history)
    assert len(rows) == 2
    assert all(row["source"] == "self_improvement" for row in rows)
    assert all("execution_authorized" not in row for row in rows)
    assert all("ignored user text" not in json.dumps(row) for row in rows)
    assert rows[0]["title"] == "Review recurring development failures"
    assert rows[1]["title"] == "Resolve safety or evidence blocks"


def test_candidate_adapter_deduplicates_same_category_and_source_id():
    history = [
        {"kind": "success", "task_id": "task-a", "detail": "task passed or verified no-change"},
        {"kind": "success", "task_id": "task-a", "detail": "task passed or verified no-change"},
    ]
    assert len(candidates_from_history(history)) == 1


def test_candidate_adapter_rejects_malformed_durable_history():
    with pytest.raises(ValueError):
        candidates_from_history([{"kind": "failure", "task_id": "bad id", "detail": "raw"}])


def test_candidate_adapter_missing_state_fails_closed_without_writing_empty_pool(tmp_path):
    output = tmp_path / "candidate-input.json"
    assert main(["--state", str(tmp_path / "missing.json"), "--output", str(output)]) == 2
    assert not output.exists()


def test_rea_observations_create_distinct_review_candidates_not_task_failures():
    rea_rows = [
        {
            "record_type": "rea_observation", "cycle_id": "20001", "task_id": "task-a",
            "gate": "PASS", "scanner_status": "FINDINGS", "category": "nonblocking_findings",
            "finding_count": 2, "critical_count": 0, "blocking_count": 0, "target_sha": "a" * 40,
        },
        {
            "record_type": "rea_observation", "cycle_id": "20002", "task_id": "task-b",
            "gate": "BLOCKED", "scanner_status": "FINDINGS", "category": "finding_block",
            "finding_count": 1, "critical_count": 1, "blocking_count": 1, "target_sha": "b" * 40,
        },
        {
            "record_type": "rea_observation", "cycle_id": "20003", "task_id": "task-c",
            "gate": "BLOCKED", "scanner_status": "BLOCKED", "category": "evidence_block",
            "finding_count": 0, "critical_count": 0, "blocking_count": 0, "target_sha": None,
        },
        {
            "record_type": "rea_observation", "cycle_id": "20004", "task_id": "task-d",
            "gate": "PASS", "scanner_status": "PASS", "category": "clean_scan",
            "finding_count": 0, "critical_count": 0, "blocking_count": 0, "target_sha": "c" * 40,
        },
    ]
    rows = candidates_from_history([], rea_rows)
    assert len(rows) == 3
    assert all(row["source"] == "self_improvement" for row in rows)
    assert all(row["status"] == "proposed" for row in rows)
    assert {row["title"] for row in rows} == {
        "Review non-blocking REA findings",
        "Review REA high-severity evidence",
        "Improve REA evidence completeness",
    }
    assert all("developer" in row["rationale"] and "failure" in row["rationale"] for row in rows)
    assert all("execution_authorized" not in row for row in rows)
    assert "task-a" not in json.dumps(rows)


def test_rea_candidate_adapter_rejects_tampered_observation():
    bad = [{
        "record_type": "rea_observation", "cycle_id": "20005", "task_id": "task-a",
        "gate": "BLOCKED", "scanner_status": "FINDINGS", "category": "finding_block",
        "finding_count": 1, "critical_count": 1, "blocking_count": 1,
        "target_sha": "a" * 40, "execution_authorized": True,
    }]
    with pytest.raises(ValueError):
        candidates_from_history([], bad)


def test_candidate_adapter_reads_rea_observations_from_durable_state(tmp_path):
    state = tmp_path / "state.json"
    output = tmp_path / "candidate-input.json"
    state.write_text(json.dumps({
        "self_improvement_history": [],
        "rea_observations": [{
            "record_type": "rea_observation", "cycle_id": "20006", "task_id": "task-a",
            "gate": "BLOCKED", "scanner_status": "BLOCKED", "category": "evidence_block",
            "finding_count": 0, "critical_count": 0, "blocking_count": 0, "target_sha": None,
        }],
    }), encoding="utf-8")
    assert main(["--state", str(state), "--output", str(output)]) == 0
    rows = json.loads(output.read_text(encoding="utf-8"))
    assert len(rows) == 1
    assert rows[0]["title"] == "Improve REA evidence completeness"
    assert rows[0]["source_id"].startswith("rea-observation:evidence_block:20006:")
