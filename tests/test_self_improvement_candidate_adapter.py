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


def test_candidate_adapter_missing_state_writes_empty_list(tmp_path):
    output = tmp_path / "candidate-input.json"
    assert main(["--state", str(tmp_path / "missing.json"), "--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == []
