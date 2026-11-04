import pytest

from goal_job_review_queue import _bounded_child_snapshot
from scripts import mac_bonsai_goal_review_worker as worker
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



def test_worker_rejects_truncated_child_evidence():
    review = {
        "objective": "do not infer from a partial evidence set",
        "success_criteria": [{"id": "artifact", "description": "Artifact is verified"}],
        "children": [{
            "goal_job_key": "job-1",
            "status": "completed",
            "evidence": {"checks": [], "truncated": True},
            "result": "partial",
        }],
    }
    with pytest.raises(ReviewWorkerError, match="truncated"):
        _bounded_review_input(review)


def test_worker_rejects_omitted_child_jobs():
    review = {
        "objective": "do not infer from an incomplete child list",
        "success_criteria": [{"id": "artifact", "description": "Artifact is verified"}],
        "children": [],
        "children_truncated": True,
    }
    with pytest.raises(ReviewWorkerError, match="truncated"):
        _bounded_review_input(review)


def test_worker_rejects_duplicate_criterion_ids():
    review = {
        "objective": "criterion identity must be unambiguous",
        "success_criteria": [
            {"id": "same", "description": "first"},
            {"id": "same", "description": "second"},
        ],
        "children": [],
    }
    with pytest.raises(ReviewWorkerError, match="unique"):
        _bounded_review_input(review)



def _valid_review():
    return {
        "objective": "verify an artifact",
        "success_criteria": [{"id": "artifact", "description": "Artifact is verified"}],
        "children": [{
            "goal_job_key": "job-1",
            "status": "completed",
            "evidence": {"checks": [{"name": "test", "status": "PASS", "source": "pytest"}]},
            "result": "verified",
        }],
    }


def test_bonsai_response_accepts_exact_criterion_map(monkeypatch):
    monkeypatch.setattr(worker, "_post_json", lambda *args, **kwargs: {
        "choices": [{"message": {"content": '{"artifact":"PASS"}'}}]
    })
    assert worker._review_with_bonsai(_valid_review(), "http://127.0.0.1:8081/v1", "local") == {
        "artifact": "PASS"
    }


@pytest.mark.parametrize("content", [
    '{"artifact":"PASS","extra":"PASS"}',
    '{"artifact":"MAYBE"}',
    '{"different":"PASS"}',
    'not json',
    '',
])
def test_bonsai_response_rejects_malformed_or_ambiguous_results(monkeypatch, content):
    monkeypatch.setattr(worker, "_post_json", lambda *args, **kwargs: {
        "choices": [{"message": {"content": content}}]
    })
    with pytest.raises(ReviewWorkerError):
        worker._review_with_bonsai(_valid_review(), "http://127.0.0.1:8081/v1", "local")


def test_bonsai_response_rejects_missing_message(monkeypatch):
    monkeypatch.setattr(worker, "_post_json", lambda *args, **kwargs: {"choices": []})
    with pytest.raises(ReviewWorkerError):
        worker._review_with_bonsai(_valid_review(), "http://127.0.0.1:8081/v1", "local")


def test_worker_configuration_requires_https_api_and_local_bonsai(monkeypatch):
    monkeypatch.setattr(worker, "_keychain_secret", lambda: "")
    monkeypatch.setenv("LINE_BOT_BASE_URL", "http://line-bot.example")
    monkeypatch.setenv("INTERNAL_PUSH_KEY", "k" * 32)
    with pytest.raises(ReviewWorkerError, match="HTTPS"):
        worker._configuration()

    monkeypatch.setenv("LINE_BOT_BASE_URL", "https://line-bot.example")
    monkeypatch.setenv("BONSAI_BASE_URL", "https://remote-model.example/v1")
    with pytest.raises(ReviewWorkerError, match="localhost"):
        worker._configuration()


def test_worker_configuration_accepts_https_api_and_local_bonsai(monkeypatch):
    monkeypatch.setattr(worker, "_keychain_secret", lambda: "")
    monkeypatch.setenv("LINE_BOT_BASE_URL", "https://line-bot.example")
    monkeypatch.setenv("INTERNAL_PUSH_KEY", "k" * 32)
    monkeypatch.setenv("BONSAI_BASE_URL", "http://127.0.0.1:8081/v1")
    assert worker._configuration() == (
        "https://line-bot.example", "k" * 32,
        "http://127.0.0.1:8081/v1", "Ternary-Bonsai-2-9B-mlx-2bit"
    )
