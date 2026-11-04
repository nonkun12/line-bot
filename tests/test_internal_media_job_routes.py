import hashlib
import json

import db
import goal_job_store
from agents.video.scenario import build_scenario
from internal_goal_job_routes import register_goal_job_routes


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", str(tmp_path / "media-routes.sqlite"))
    db.init_db()
    goal_job_store.init_goal_job_store()
    app = __import__("flask").Flask(__name__)
    register_goal_job_routes(app, "media-test-key")
    return app.test_client()


def _create_media_job():
    scenario = build_scenario("夜明けの街", duration_seconds=15, scene_count=3)
    job = {
        "id": "media-bundle",
        "criterion_id": "media-artifact",
        "stage": "design",
        "instruction": "Create a local-only audiovisual draft bundle.",
        "allowed_paths": ["docs/goal-plans/media-bundle.md"],
        "depends_on": [],
        "executor": "mac_local_media.v1",
        "operation": "create_audiovisual_bundle",
        "scenario": scenario,
    }
    goal = {
        "goal_id": "media-route-goal",
        "objective": "Create a local audiovisual draft bundle",
        "success_criteria": [{
            "id": "media-artifact",
            "description": "The local media bundle has validated artifact hashes",
        }],
        "jobs": [job],
    }
    grant = {
        "grant_id": "media-route-grant",
        "goal_id": "media-route-goal",
        "active": True,
        "approved_by": "test-owner",
        "expires_at": "2099-01-01T00:00:00Z",
        "auto_approve_registered_jobs": True,
        "max_jobs": 2,
        "allowed_stages": ["design"],
        "allowed_path_prefixes": ["docs/"],
        "auto_merge": False,
        "auto_deploy": False,
    }
    goal_job_store.create_goal(goal, "U-media-test", grant)
    return goal_job_store.persist_child_job("media-route-goal", job)["job_id"]


def test_media_claim_requires_internal_key_and_claims_only_typed_executor(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    job_id = _create_media_job()
    assert client.post("/internal/media-jobs/claim").status_code == 401
    response = client.post(
        "/internal/media-jobs/claim",
        headers={"x-internal-key": "media-test-key"},
        json={},
    )
    body = response.get_json()
    assert response.status_code == 200
    assert body["claimed"] is True
    assert body["job"]["id"] == job_id
    assert body["job"]["payload"]["executor"] == "mac_local_media.v1"
    assert body["lease_seconds"] == 1800
    second = client.post(
        "/internal/media-jobs/claim",
        headers={"x-internal-key": "media-test-key"},
        json={},
    )
    assert second.get_json()["claimed"] is False


def test_media_completion_requires_matching_receipt_and_artifact_hashes(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    job_id = _create_media_job()
    headers = {"x-internal-key": "media-test-key"}
    claimed = client.post("/internal/media-jobs/claim", headers=headers, json={}).get_json()["job"]
    hashes = {
        "scenario": "a" * 64,
        "music_plan": "b" * 64,
        "midi": "c" * 64,
        "audio_preview": "d" * 64,
        "video_edit_decision_list": "e" * 64,
    }
    receipt = {
        "schema_version": "mac-local-media-receipt.v1",
        "executor": "mac_local_media.v1",
        "operation": "create_audiovisual_bundle",
        "goal_job_id": job_id,
        "idempotency_key": hashlib.sha256(f"mac_local_media.v1:{job_id}".encode()).hexdigest(),
        "status": "draft",
        "artifact_sha256": hashes,
        "video_render_status": "not_rendered",
        "publication": "not_performed",
    }
    result = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
    evidence = {
        "executor": "mac_local_media.v1",
        "goal_job_id": job_id,
        "artifact_sha256": hashes,
        "receipt_sha256": "f" * 64,
        "checks": [{
            "name": "artifact_inventory_and_sha256",
            "status": "PASS",
            "source": "mac_local_media.v1",
        }],
    }
    invalid = dict(evidence, artifact_sha256={"midi": "0" * 64})
    rejected = client.post("/internal/media-jobs/complete", headers=headers, json={
        "job_id": job_id,
        "claim_token": claimed["claim_token"],
        "result": result,
        "evidence": invalid,
    })
    assert rejected.status_code == 400
    assert db.get_job(job_id)["status"] == "running"

    completed = client.post("/internal/media-jobs/complete", headers=headers, json={
        "job_id": job_id,
        "claim_token": claimed["claim_token"],
        "result": result,
        "evidence": evidence,
    })
    assert completed.status_code == 200
    assert completed.get_json()["completed"] is True
    assert goal_job_store.get_goal("media-route-goal")["status"] == "achieved"
    duplicate = client.post("/internal/media-jobs/complete", headers=headers, json={
        "job_id": job_id,
        "claim_token": claimed["claim_token"],
        "result": result,
        "evidence": evidence,
    })
    assert duplicate.status_code == 409


def test_media_claim_ignores_untyped_goal_child(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _create_media_job()
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET message=? WHERE id=(SELECT MIN(id) FROM jobs)",
            (json.dumps({"goal_id": "media-route-goal", "goal_job_key": "untyped"}),),
        )
    response = client.post(
        "/internal/media-jobs/claim",
        headers={"x-internal-key": "media-test-key"},
        json={},
    )
    assert response.status_code == 200
    assert response.get_json()["claimed"] is False
