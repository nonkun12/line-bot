import json

import db
import goal_job_store
import internal_goal_job_routes as goal_routes
from internal_goal_job_routes import register_goal_job_routes


def _app(tmp_path, monkeypatch, *, independent_goal_evaluator=None):
    monkeypatch.setattr(db, "DB", str(tmp_path / "goal-routes.sqlite"))
    db.init_db()
    goal_job_store.init_goal_job_store()
    app = __import__("flask").Flask(__name__)
    register_goal_job_routes(app, "test-internal-key", independent_goal_evaluator=independent_goal_evaluator)
    return app.test_client()


def _create_goal():
    goal = {
        "goal_id": "route-goal",
        "objective": "test internal goal worker transport",
        "success_criteria": [{"id": "criterion", "description": "worker result is persisted"}],
        "jobs": [{
            "id": "child-1", "criterion_id": "criterion", "stage": "test",
            "instruction": "Add one focused test.",
            "allowed_paths": ["tests/test_internal_goal_job_routes.py"],
            "depends_on": [],
        }],
    }
    grant = {
        "grant_id": "route-grant", "goal_id": "route-goal", "active": True,
        "approved_by": "test-owner", "expires_at": "2099-01-01T00:00:00Z",
        "auto_approve_registered_jobs": True, "max_jobs": 2,
        "allowed_stages": ["test"],
        "allowed_path_prefixes": ["tests/"],
        "auto_merge": False, "auto_deploy": False,
    }
    goal_job_store.create_goal(goal, "U-test", grant)
    return goal_job_store.persist_child_job("route-goal", goal["jobs"][0])["job_id"]


def test_claim_requires_internal_key_and_returns_only_authorized_goal_job(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    job_id = _create_goal()
    assert client.post("/internal/goal-jobs/claim", json={"job_id": job_id}).status_code == 401
    response = client.post(
        "/internal/goal-jobs/claim",
        headers={"x-internal-key": "test-internal-key"},
        json={"job_id": job_id},
    )
    body = response.get_json()
    assert response.status_code == 200
    assert body["claimed"] is True
    assert body["job"]["id"] == job_id
    assert body["job"]["payload"]["goal_id"] == "route-goal"
    assert body["job"]["claim_token"]


def test_claim_is_atomic_and_second_worker_gets_no_job(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    job_id = _create_goal()
    headers = {"x-internal-key": "test-internal-key"}
    first = client.post("/internal/goal-jobs/claim", headers=headers, json={"job_id": job_id}).get_json()
    second = client.post("/internal/goal-jobs/claim", headers=headers, json={"job_id": job_id}).get_json()
    assert first["claimed"] is True
    assert second["claimed"] is False


def test_complete_requires_claim_token_and_is_idempotently_rejected_after_first_write(tmp_path, monkeypatch):
    monkeypatch.setattr(goal_routes, "_verify_exact_sha_checks", lambda evidence, sha: True)
    client = _app(tmp_path, monkeypatch)
    job_id = _create_goal()
    headers = {"x-internal-key": "test-internal-key"}
    claimed = client.post("/internal/goal-jobs/claim", headers=headers, json={"job_id": job_id}).get_json()["job"]
    payload = {
        "job_id": job_id,
        "claim_token": claimed["claim_token"],
        "success": True,
        "result": json.dumps({"produced_sha": "a" * 40}),
        "evidence": {
            "produced_sha": "a" * 40,
            "checks": [{"name": "guarded_runtime", "status": "PASS", "source": "worker"}],
            "verification": {
                "target_sha": "a" * 40,
                "pytest_status": "PASS",
                "review_status": "PASS",
                "pytest_run_url": "https://github.com/nonkun12/line-bot/actions/runs/123",
                "review_run_url": "https://github.com/nonkun12/line-bot/actions/runs/124",
            },
        },
    }
    first = client.post("/internal/goal-jobs/complete", headers=headers, json=payload)
    second = client.post("/internal/goal-jobs/complete", headers=headers, json=payload)
    assert first.status_code == 200
    assert first.get_json()["continuation"]["decision"] == "GOAL_ACHIEVED"
    assert goal_job_store.get_goal("route-goal")["status"] == "achieved"
    assert second.status_code == 409


def test_failed_checks_cannot_be_reported_as_success(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    job_id = _create_goal()
    headers = {"x-internal-key": "test-internal-key"}
    claimed = client.post("/internal/goal-jobs/claim", headers=headers, json={"job_id": job_id}).get_json()["job"]
    response = client.post("/internal/goal-jobs/complete", headers=headers, json={
        "job_id": job_id, "claim_token": claimed["claim_token"], "success": True,
        "result": "not passed",
        "evidence": {"checks": [{"name": "runtime", "status": "FAIL", "source": "worker"}]},
    })
    assert response.status_code == 200
    assert response.get_json()["success"] is False
    assert db.get_job(job_id)["status"] == "failed"


def test_success_is_rejected_without_independent_exact_sha_verification(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    job_id = _create_goal()
    headers = {"x-internal-key": "test-internal-key"}
    claimed = client.post("/internal/goal-jobs/claim", headers=headers, json={"job_id": job_id}).get_json()["job"]
    response = client.post("/internal/goal-jobs/complete", headers=headers, json={
        "job_id": job_id,
        "claim_token": claimed["claim_token"],
        "success": True,
        "result": "runtime finished",
        "evidence": {
            "produced_sha": "b" * 40,
            "checks": [{"name": "guarded_runtime", "status": "PASS", "source": "worker"}],
        },
    })
    assert response.status_code == 400
    assert db.get_job(job_id)["status"] == "running"



def test_github_run_verifier_requires_exact_sha_and_success(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({
                "id": 123,
                "name": "Pytest",
                "head_sha": "a" * 40,
                "status": "completed",
                "conclusion": "success",
            }).encode()

    monkeypatch.setattr(goal_routes.urllib.request, "urlopen", lambda request, timeout: FakeResponse())
    assert goal_routes._github_run_passed(
        "https://github.com/nonkun12/line-bot/actions/runs/123",
        "Pytest",
        "a" * 40,
    )
    assert not goal_routes._github_run_passed(
        "https://github.com/nonkun12/line-bot/actions/runs/123",
        "Pytest",
        "b" * 40,
    )
    assert not goal_routes._github_run_passed(
        "https://example.com/actions/runs/123",
        "Pytest",
        "a" * 40,
    )


def test_github_run_verifier_fails_closed_on_api_error(monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("network unavailable")

    monkeypatch.setattr(goal_routes.urllib.request, "urlopen", unavailable)
    assert not goal_routes._github_run_passed(
        "https://github.com/nonkun12/line-bot/actions/runs/123",
        "Pytest",
        "a" * 40,
    )

def test_completion_invokes_injected_independent_goal_reviewer_with_persisted_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(goal_routes, "_verify_exact_sha_checks", lambda evidence, sha: True)
    reviewed = []

    def independent_evaluator(record, children):
        reviewed.append((record["goal_id"], children))
        assert children[0]["evidence"]["checks"][0]["status"] == "PASS"
        assert children[0]["evidence"]["verification"]["target_sha"] == "c" * 40
        return {"criterion": "PASS"}

    client = _app(
        tmp_path, monkeypatch,
        independent_goal_evaluator=independent_evaluator,
    )
    job_id = _create_goal()
    headers = {"x-internal-key": "test-internal-key"}
    claimed = client.post(
        "/internal/goal-jobs/claim", headers=headers, json={"job_id": job_id}
    ).get_json()["job"]
    evidence = {
        "produced_sha": "c" * 40,
        "checks": [{"name": "guarded_runtime", "status": "PASS", "source": "worker"}],
        "verification": {
            "target_sha": "c" * 40,
            "pytest_status": "PASS",
            "review_status": "PASS",
            "pytest_run_url": "https://github.com/nonkun12/line-bot/actions/runs/123",
            "review_run_url": "https://github.com/nonkun12/line-bot/actions/runs/124",
        },
    }
    response = client.post("/internal/goal-jobs/complete", headers=headers, json={
        "job_id": job_id,
        "claim_token": claimed["claim_token"],
        "success": True,
        "result": "verified completion",
        "evidence": evidence,
    })

    assert response.status_code == 200
    assert response.get_json()["continuation"]["reviewed"] is True
    assert reviewed and reviewed[0][0] == "route-goal"
    assert goal_job_store.get_goal("route-goal")["status"] == "achieved"
