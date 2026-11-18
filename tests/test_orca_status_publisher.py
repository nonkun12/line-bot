import hashlib
import hmac
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
from scripts.orca_status_publisher import publish_snapshot, validate_snapshot


def payload():
    return {"captured_at": datetime.now(timezone.utc).isoformat(), "run_id": "r1",
            "tasks": [{"id": "t1", "prompt": "SECRET"}], "dispatches": [], "workers": [],
            "streams": [{"key": "main_star_night", "label": "STAR-NIGHT", "kind": "main",
                         "status": "unknown", "task_count": 0, "dispatch_count": 0,
                         "worker_count": 0, "evidence": "no_matching_stream_metadata"}]}


def test_validate_snapshot_redacts_unknown_fields():
    clean = validate_snapshot(payload())
    assert clean["tasks"] == [{"id": "t1"}]
    assert len(clean["streams"]) == 1


@pytest.mark.parametrize("captured", [None, "not-a-date", "2026-01-01T00:00:00",
    (datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat(),
    (datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()])
def test_validate_snapshot_rejects_invalid_or_stale_timestamps(captured):
    data = payload()
    data["captured_at"] = captured
    with pytest.raises(ValueError): validate_snapshot(data)


def test_validate_snapshot_rejects_bad_collection_and_stream_shapes():
    data = payload()
    data["workers"] = ["not-object"]
    with pytest.raises(ValueError): validate_snapshot(data)
    data = payload()
    data["streams"][0]["key"] = "unexpected"
    with pytest.raises(ValueError): validate_snapshot(data)


def test_publish_snapshot_signs_sanitized_payload_and_posts_https():
    data = payload()
    captured = {}
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
    def fake_urlopen(request, timeout):
        captured.update(url=request.full_url, body=request.data, signature=request.get_header("X-orca-signature"))
        return Response()
    with patch("scripts.orca_status_publisher.urlopen", fake_urlopen):
        assert publish_snapshot("https://dashboard.example", "secret", data) == 200
    assert captured["url"] == "https://dashboard.example/internal/orca/status"
    assert captured["signature"] == hmac.new(b"secret", captured["body"], hashlib.sha256).hexdigest()
    assert "SECRET" not in captured["body"].decode()


def test_publish_snapshot_refuses_http_and_missing_secret():
    with pytest.raises(ValueError): publish_snapshot("http://dashboard.example", "secret", payload())
    with pytest.raises(ValueError): publish_snapshot("https://dashboard.example", "", payload())


def test_validate_snapshot_accepts_sixth_core_vocabulary_stream():
    data = payload()
    data["streams"].append({
        "key": "side_core_vocabulary", "label": "英単語コア語彙", "kind": "side",
        "status": "observed", "task_count": 1, "dispatch_count": 0,
        "worker_count": 0, "evidence": "matched_runtime_records",
    })
    clean = validate_snapshot(data)
    assert len(clean["streams"]) == 2
    assert clean["streams"][1]["key"] == "side_core_vocabulary"


def test_validate_snapshot_accepts_fail_closed_rsi_review_summary():
    data = payload()
    data["rsi_review"] = {"status": "PASS", "review_count": 1, "review_evidence_event_ids": ["orchestra-rea:event-1"],
        "proposal_only": True, "allow_continue": False, "execution_authorized": False,
        "patch_authorized": False, "hold_clear_authorized": False, "merge_deploy_authorized": False,
        "scheduler_started": False, "model_activated": False, "raw_feedback": "secret"}
    clean = validate_snapshot(data)
    assert clean["rsi_review"]["status"] == "PASS"
    assert "raw_feedback" not in clean["rsi_review"]


@pytest.mark.parametrize("field", ["allow_continue", "execution_authorized", "patch_authorized",
    "hold_clear_authorized", "merge_deploy_authorized", "scheduler_started", "model_activated"])
def test_validate_snapshot_rejects_rsi_authority_escalation(field):
    data = payload()
    data["rsi_review"] = {"status": "PASS", "review_count": 0, "review_evidence_event_ids": [],
        "proposal_only": True, "allow_continue": False, "execution_authorized": False,
        "patch_authorized": False, "hold_clear_authorized": False, "merge_deploy_authorized": False,
        "scheduler_started": False, "model_activated": False}
    data["rsi_review"][field] = True
    with pytest.raises(ValueError): validate_snapshot(data)

def test_validate_snapshot_accepts_safe_rea_artifact_fields():
    data = payload()
    data["tasks"] = [{
        "task_id": "t-rea",
        "rea_artifact_status": "HOLD",
        "rea_artifact_reason_code": "risk_unknown",
        "rea_artifact_evidence_sha256": "b" * 64,
        "rea_artifact_execution_authorized": False,
        "rea_artifact_patch_authorized": False,
        "rea_artifact_hold_clear_authorized": False,
        "rea_artifact_merge_deploy_authorized": False,
        "raw_diff": "must not leak",
    }]
    clean = validate_snapshot(data)
    task = clean["tasks"][0]
    assert task["rea_artifact_status"] == "HOLD"
    assert task["rea_artifact_evidence_sha256"] == "b" * 64
    assert "raw_diff" not in task


def test_validate_snapshot_rejects_rea_authority_escalation_and_bad_hash():
    data = payload()
    data["tasks"] = [{
        "task_id": "t-rea", "rea_artifact_status": "PASS",
        "rea_artifact_evidence_sha256": "c" * 64,
        "rea_artifact_execution_authorized": True,
        "rea_artifact_patch_authorized": False,
        "rea_artifact_hold_clear_authorized": False,
        "rea_artifact_merge_deploy_authorized": False,
    }]
    with pytest.raises(ValueError):
        validate_snapshot(data)
    data["tasks"][0]["rea_artifact_execution_authorized"] = False
    data["tasks"][0]["rea_artifact_evidence_sha256"] = "bad"
    with pytest.raises(ValueError):
        validate_snapshot(data)


def test_validate_snapshot_keeps_work_finder_counts_separate_and_review_only():
    data = payload()
    data["work_finder"] = {
        "cycle_status": "WORK_FOUND", "next_action": "human_review_candidates",
        "execution_eligibility_status": "not_proven",
        "candidate_policy": "review_only_no_execution_approval",
        "safety": {"read_only": True, "execution_approval_granted": False},
        "discovered_candidate_count": 2, "review_pending_count": 2,
        "completed_task_count": 5, "catalog_task_count": 30,
        "runtime_queue_task_count": 0, "held_task_count": 4,
        "resume_review_required_count": 1, "scanned_target_pairs": 9,
        "candidate_preview": [{"id": "review-coverage-gap-a1b2", "target_test": "tests/test_x.py", "source_function": "do_work", "evidence": "core/x.py:12", "status": "REVIEW_REQUIRED"}],
    }
    clean = validate_snapshot(data)
    assert clean["work_finder"]["discovered_candidate_count"] == 2
    assert clean["work_finder"]["review_pending_count"] == 2
    assert "execution_eligible_count" not in clean["work_finder"]
    assert clean["work_finder"]["completed_task_count"] == 5
    assert clean["work_finder"]["candidate_preview"][0]["source_function"] == "do_work"
    data["work_finder"]["safety"]["execution_approval_granted"] = True
    with pytest.raises(ValueError):
        validate_snapshot(data)
