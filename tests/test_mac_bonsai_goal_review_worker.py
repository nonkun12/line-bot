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
        "objective": "verify artifact",
        "success_criteria": [{"id": "artifact", "description": "Artifact is verified"}],
        "children": [{
            "goal_job_key": "job-1",
            "status": "completed",
            "evidence": {"checks": [{"name": "test", "status": "PASS", "source": "pytest"}]},
            "result": "verified",
        }],
    }


def test_bonsai_review_rejects_extra_or_missing_criterion_keys(monkeypatch):
    import scripts.mac_bonsai_goal_review_worker as worker

    monkeypatch.setattr(worker, "_post_json", lambda *a, **k: {
        "choices": [{"message": {"content": '{"artifact":"PASS","extra":"PASS"}'}}]
    })
    with pytest.raises(ReviewWorkerError, match="cover every criterion"):
        worker._review_with_bonsai(_valid_review(), "http://127.0.0.1:8081/v1", "local")


def test_bonsai_review_rejects_non_json_response(monkeypatch):
    import scripts.mac_bonsai_goal_review_worker as worker

    monkeypatch.setattr(worker, "_post_json", lambda *a, **k: {
        "choices": [{"message": {"content": "PASS, looks good"}}]
    })
    with pytest.raises(ReviewWorkerError, match="strict JSON"):
        worker._review_with_bonsai(_valid_review(), "http://127.0.0.1:8081/v1", "local")


def test_configuration_rejects_non_local_bonsai_endpoint(monkeypatch):
    import scripts.mac_bonsai_goal_review_worker as worker

    monkeypatch.setenv("LINE_BOT_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("INTERNAL_PUSH_KEY", "x" * 32)
    monkeypatch.setenv("BONSAI_BASE_URL", "http://192.168.1.20:8081/v1")
    with pytest.raises(ReviewWorkerError, match="localhost"):
        worker._configuration()


def test_configuration_rejects_non_https_server_origin(monkeypatch):
    import scripts.mac_bonsai_goal_review_worker as worker

    monkeypatch.setenv("LINE_BOT_BASE_URL", "http://example.invalid")
    monkeypatch.setenv("INTERNAL_PUSH_KEY", "x" * 32)
    with pytest.raises(ReviewWorkerError, match="HTTPS origin"):
        worker._configuration()


def test_post_json_rejects_oversized_response(monkeypatch):
    import scripts.mac_bonsai_goal_review_worker as worker

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return b"x" * limit

    class FakeOpener:
        def open(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(worker, "build_opener", lambda *handlers: FakeOpener())
    with pytest.raises(ReviewWorkerError, match="size limit"):
        worker._post_json("https://example.invalid", {})


def test_bonsai_timeout_is_submitted_as_unknown_not_pass(monkeypatch):
    import scripts.mac_bonsai_goal_review_worker as worker

    calls = []

    def fake_post(url, payload, *, key=None, timeout=30):
        calls.append((url, payload, key, timeout))
        if url.endswith("/claim"):
            return {
                "claimed": True,
                "review": {
                    "review_id": 7,
                    "claim_token": "t" * 32,
                    "goal_id": "goal-7",
                    "success_criteria": [{"id": "artifact", "description": "verified"}],
                    "children": [],
                },
            }
        return {"decision": {"decision": "HOLD"}}

    monkeypatch.setattr(worker, "_post_json", fake_post)
    monkeypatch.setattr(
        worker, "_review_with_bonsai",
        lambda *args: (_ for _ in ()).throw(worker.ReviewWorkerError("Bonsai timeout")),
    )

    assert worker.run_once("https://line.example", "k" * 32, "http://127.0.0.1:8081/v1", "local")
    assert calls[-1][1]["criterion_results"] == {"artifact": "UNKNOWN"}
    assert calls[-1][2] == "k" * 32


def test_bonsai_completion_transport_failure_is_not_silently_retried(monkeypatch):
    import scripts.mac_bonsai_goal_review_worker as worker

    calls = []

    def fake_post(url, payload, *, key=None, timeout=30):
        calls.append(url)
        if url.endswith("/claim"):
            return {
                "claimed": True,
                "review": {
                    "review_id": 8,
                    "claim_token": "u" * 32,
                    "goal_id": "goal-8",
                    "success_criteria": [{"id": "artifact", "description": "verified"}],
                    "children": [],
                },
            }
        raise worker.ReviewWorkerError("completion endpoint unavailable")

    monkeypatch.setattr(worker, "_post_json", fake_post)
    monkeypatch.setattr(worker, "_review_with_bonsai", lambda *args: {"artifact": "PASS"})

    with pytest.raises(ReviewWorkerError, match="completion endpoint unavailable"):
        worker.run_once("https://line.example", "k" * 32, "http://127.0.0.1:8081/v1", "local")
    assert len(calls) == 2


def test_worker_rejects_more_than_twelve_child_jobs_instead_of_dropping_evidence():
    review = _valid_review()
    review["children"] = [
        {
            "goal_job_key": f"job-{index}",
            "status": "completed",
            "evidence": {"checks": [{"name": "test", "status": "PASS"}]},
            "result": "verified",
        }
        for index in range(13)
    ]
    with pytest.raises(ReviewWorkerError, match="12-job"):
        _bounded_review_input(review)


def test_worker_rejects_malformed_child_job_instead_of_skipping_it():
    review = _valid_review()
    review["children"].append("malformed child")
    with pytest.raises(ReviewWorkerError, match="malformed"):
        _bounded_review_input(review)


def test_worker_rejects_child_without_persisted_evidence():
    review = _valid_review()
    review["children"][0]["evidence"] = None
    with pytest.raises(ReviewWorkerError, match="persisted evidence"):
        _bounded_review_input(review)


def test_post_json_rejects_redirects_without_following_them(monkeypatch):
    import scripts.mac_bonsai_goal_review_worker as worker
    from urllib.error import HTTPError

    class FakeOpener:
        def open(self, request, timeout=30):
            assert request.get_header("X-internal-key") == "s" * 32
            raise HTTPError(request.full_url, 302, "redirect rejected", {}, None)

    monkeypatch.setattr(worker, "build_opener", lambda *handlers: FakeOpener())
    with pytest.raises(ReviewWorkerError, match="HTTP 302"):
        worker._post_json(
            "https://line.example/internal/goal-review/claim",
            {},
            key="s" * 32,
        )


def test_configuration_rejects_credentials_embedded_in_server_origin(monkeypatch):
    import scripts.mac_bonsai_goal_review_worker as worker

    monkeypatch.setenv("LINE_BOT_BASE_URL", "https://user:password@example.invalid")
    monkeypatch.setenv("INTERNAL_PUSH_KEY", "x" * 32)
    monkeypatch.setenv("BONSAI_BASE_URL", "http://127.0.0.1:8081/v1")
    with pytest.raises(ReviewWorkerError, match="without embedded credentials"):
        worker._configuration()
