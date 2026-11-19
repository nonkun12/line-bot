from flask import Flask

from routes.obsidian_bridge import obsidian_bridge_bp


def make_app():
    app = Flask(__name__)
    app.register_blueprint(obsidian_bridge_bp)
    return app


def test_claim_requires_bridge_key(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_BRIDGE_KEY", "secret")
    response = make_app().test_client().post("/api/obsidian/claim", json={})
    assert response.status_code == 401
    assert response.get_json()["error"] == "unauthorized"


def test_claim_returns_one_job(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_BRIDGE_KEY", "secret")
    import routes.obsidian_bridge as bridge

    monkeypatch.setattr(
        bridge,
        "claim_pending_job_by_type",
        lambda job_type: {
            "id": 7,
            "user_id": "U1",
            "message": "Obsidian一覧",
            "claim_token": "token",
        },
    )

    response = make_app().test_client().post(
        "/api/obsidian/claim",
        json={},
        headers={"X-Obsidian-Bridge-Key": "secret"},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "job": {
            "id": 7,
            "user_id": "U1",
            "message": "Obsidian一覧",
            "claim_token": "token",
        },
    }


def test_complete_rejects_invalid_payload(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_BRIDGE_KEY", "secret")
    response = make_app().test_client().post(
        "/api/obsidian/complete",
        json={"job_id": 1, "claim_token": "t", "success": "yes"},
        headers={"X-Obsidian-Bridge-Key": "secret"},
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "success must be boolean"


def test_complete_rejects_wrong_claim(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_BRIDGE_KEY", "secret")
    import routes.obsidian_bridge as bridge

    monkeypatch.setattr(
        bridge,
        "get_job",
        lambda job_id: {
            "id": job_id,
            "job_type": "obsidian",
            "status": "running",
            "user_id": "U1",
        },
    )
    monkeypatch.setattr(bridge, "complete_claimed_job", lambda *args, **kwargs: False)

    response = make_app().test_client().post(
        "/api/obsidian/complete",
        json={"job_id": 1, "claim_token": "wrong", "success": True, "reply": "x"},
        headers={"X-Obsidian-Bridge-Key": "secret"},
    )
    assert response.status_code == 409
    assert response.get_json()["error"] == "claim token rejected"
