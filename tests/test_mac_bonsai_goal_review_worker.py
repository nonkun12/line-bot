import pytest

from goal_job_review_queue import _bounded_child_snapshot
from scripts.mac_bonsai_goal_review_worker import ReviewWorkerError, _bounded_review_input


def test_review_snapshot_limits_child_count_and_marks_truncated_evidence():
    children = [
        {
            "goal_job_key": f"job-{index}",
            "job_id": f"id-{index}",
            "status": "completed",
            "evidence": {
                "checks": [
                    {"name": f"check-{check}", "status": "PASS", "source": "test", "detail": "x" * 700}
                    for check in range(30)
                ],
            },
            "result": "ok",
        }
        for index in range(15)
    ]
    snapshot = _bounded_child_snapshot(children)
    assert len(snapshot) == 12
    assert len(snapshot[0]["evidence"]["checks"]) == 20
    assert snapshot[0]["evidence"]["truncated"] is True


def test_worker_rejects_review_input_over_total_payload_limit():
    review = {
        "objective": "bounded payload test",
        "success_criteria": [
            {"id": f"criterion-{index}", "description": "x" * 1000}
            for index in range(40)
        ],
        "children": [],
    }
    with pytest.raises(ReviewWorkerError, match="24 KiB"):
        _bounded_review_input(review)


def test_worker_accepts_small_review_input():
    review = {
        "objective": "check one artifact",
        "success_criteria": [{"id": "artifact", "description": "Artifact is verified"}],
        "children": [{
            "goal_job_key": "job-1",
            "status": "completed",
            "evidence": {"checks": [{"name": "test", "status": "PASS", "source": "pytest"}]},
            "result": "verified",
        }],
    }
    bounded = _bounded_review_input(review)
    assert bounded["criteria"][0]["id"] == "artifact"
    assert bounded["completed_job_evidence"][0]["evidence"]["checks"][0]["status"] == "PASS"
