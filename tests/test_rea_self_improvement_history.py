from __future__ import annotations

import json

import pytest

from scripts.rea_self_improvement_history import (
    append_rea_observations,
    validate_durable_rea_observations,
)

SHA = "a" * 40


def pass_rea(*, findings=0):
    visible = [{
        "finding_id": f"{i:016x}", "category": "python_syntax",
        "severity": "MEDIUM", "path": "scripts/example.py", "line": 12,
        "status": "REVIEW_REQUIRED",
    } for i in range(findings)]
    return {
        "gate": "PASS", "mode": "OBSERVE_ONLY", "target_sha": SHA,
        "scanner_status": "FINDINGS" if findings else "PASS",
        "finding_count": findings, "critical_count": 0, "blocking_count": 0,
        "findings_truncated": False, "findings": visible,
        "execution_authorized": False, "patch_authorized": False,
        "hold_clear_authorized": False, "merge_deploy_authorized": False,
    }


def blocked_rea():
    return {
        "gate": "BLOCKED", "reason_code": "rea_high_or_critical_finding",
        "target_sha": SHA, "scanner_status": "FINDINGS",
        "finding_count": 1, "critical_count": 1, "blocking_count": 1,
        "findings_truncated": False,
        "findings": [{
            "finding_id": "b" * 16, "category": "safety_flag",
            "severity": "CRITICAL", "path": ".github/workflows/example.yml",
            "line": 4, "status": "REVIEW_REQUIRED",
        }],
        "execution_authorized": False, "patch_authorized": False,
        "hold_clear_authorized": False, "merge_deploy_authorized": False,
    }


def test_persists_clean_and_nonblocking_rea_observations_separately(tmp_path):
    history, results, catalog = tmp_path / "rea.jsonl", tmp_path / "results.jsonl", tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tasks": [{"id": "task-a"}, {"id": "task-b"}]}), encoding="utf-8")
    results.write_text("\n".join([
        json.dumps({"task_id": "task-a", "base_sha": SHA, "status": "PASS", "rea": pass_rea()}),
        json.dumps({"task_id": "task-b", "base_sha": SHA, "status": "PASS", "rea": pass_rea(findings=1)}),
    ]) + "\n", encoding="utf-8")

    assert append_rea_observations(history, results, catalog, cycle_id="10001") == 2
    rows = [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines()]
    assert [row["category"] for row in rows] == ["clean_scan", "nonblocking_findings"]
    assert all(row["record_type"] == "rea_observation" for row in rows)
    assert all(row["target_sha"] == SHA for row in rows)
    assert "severity" not in history.read_text(encoding="utf-8")


def test_rea_block_is_recorded_as_evidence_category_not_developer_failure(tmp_path):
    history, results, catalog = tmp_path / "rea.jsonl", tmp_path / "results.jsonl", tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tasks": [{"id": "task-a"}]}), encoding="utf-8")
    results.write_text(json.dumps({
        "task_id": "task-a", "base_sha": SHA, "status": "BLOCKED",
        "failure_reason": "control_tower_rea:rea_high_or_critical_finding",
        "rea": blocked_rea(),
    }) + "\n", encoding="utf-8")

    assert append_rea_observations(history, results, catalog, cycle_id="10002") == 1
    row = json.loads(history.read_text(encoding="utf-8").splitlines()[0])
    assert row["category"] == "finding_block"
    assert row["gate"] == "BLOCKED"
    assert row["blocking_count"] == 1
    assert "failure" not in row


def test_append_is_idempotent_for_same_run_and_task(tmp_path):
    history, results, catalog = tmp_path / "rea.jsonl", tmp_path / "results.jsonl", tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tasks": [{"id": "task-a"}]}), encoding="utf-8")
    results.write_text(json.dumps({"task_id": "task-a", "base_sha": SHA, "rea": pass_rea()}) + "\n", encoding="utf-8")
    assert append_rea_observations(history, results, catalog, cycle_id="10003") == 1
    assert append_rea_observations(history, results, catalog, cycle_id="10003") == 0
    assert len(history.read_text(encoding="utf-8").splitlines()) == 1


def test_unknown_block_reason_and_authority_grant_fail_closed(tmp_path):
    history, results, catalog = tmp_path / "rea.jsonl", tmp_path / "results.jsonl", tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tasks": [{"id": "task-a"}]}), encoding="utf-8")
    invalid = blocked_rea()
    invalid["reason_code"] = "arbitrary_runtime_failure"
    results.write_text(json.dumps({"task_id": "task-a", "base_sha": SHA, "rea": invalid}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="independent validation"):
        append_rea_observations(history, results, catalog, cycle_id="10004")
    invalid["reason_code"] = "rea_high_or_critical_finding"
    invalid["execution_authorized"] = True
    results.write_text(json.dumps({"task_id": "task-a", "base_sha": SHA, "rea": invalid}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="independent validation"):
        append_rea_observations(history, results, catalog, cycle_id="10004")
    assert not history.exists()


def test_durable_schema_rejects_malformed_rows():
    row = {
        "record_type": "rea_observation", "cycle_id": "10005", "task_id": "task-a",
        "gate": "BLOCKED", "scanner_status": "FINDINGS", "category": "finding_block",
        "finding_count": 1, "critical_count": 1, "blocking_count": 1, "target_sha": SHA,
    }
    assert validate_durable_rea_observations([row]) == [row]
    with pytest.raises(ValueError):
        validate_durable_rea_observations([{**row, "execution_authorized": True}])
    with pytest.raises(ValueError):
        validate_durable_rea_observations([{**row, "blocking_count": True}])


def test_corrupt_history_is_not_replaced(tmp_path):
    history, results, catalog = tmp_path / "rea.jsonl", tmp_path / "results.jsonl", tmp_path / "catalog.json"
    history.write_text("{bad json}\n", encoding="utf-8")
    catalog.write_text(json.dumps({"tasks": [{"id": "task-a"}]}), encoding="utf-8")
    results.write_text(json.dumps({"task_id": "task-a", "base_sha": SHA, "rea": pass_rea()}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="refusing to overwrite"):
        append_rea_observations(history, results, catalog, cycle_id="10006")
    assert history.read_text(encoding="utf-8") == "{bad json}\n"


def test_rea_history_round_trips_through_durable_state(tmp_path):
    import sys
    from scripts.rea_self_improvement_history import main

    state = tmp_path / "state.json"
    history = tmp_path / "rea.jsonl"
    state.write_text(json.dumps({"version": 1, "rea_observations": [{
        "record_type": "rea_observation", "cycle_id": "10007", "task_id": "task-a",
        "gate": "BLOCKED", "scanner_status": "BLOCKED", "category": "evidence_block",
        "finding_count": 0, "critical_count": 0, "blocking_count": 0, "target_sha": None,
    }]}), encoding="utf-8")
    original = sys.argv
    try:
        sys.argv = ["rea_self_improvement_history.py", "import", "--state", str(state), "--history", str(history)]
        assert main() == 0
        sys.argv = ["rea_self_improvement_history.py", "export", "--state", str(state), "--history", str(history)]
        assert main() == 0
    finally:
        sys.argv = original
    durable = json.loads(state.read_text(encoding="utf-8"))
    assert durable["rea_observations"][0]["category"] == "evidence_block"
