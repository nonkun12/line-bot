import base64
from unittest.mock import patch

import pytest

from app import app
from db import init_db, save_message
from routes.dashboard import _get_oracle_n8n_status

TEST_USER_ID = "U19391b0b93be2f4d94284361153919ce"


@pytest.fixture
def auth_headers(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER", "testuser")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "testpass")
    monkeypatch.setenv("DASHBOARD_OWNER_USER_ID", TEST_USER_ID)
    token = base64.b64encode(b"testuser:testpass").decode()
    return {"Authorization": "Basic " + token}


def test_dashboard_page_status_code_and_content(auth_headers):
    init_db()
    client = app.test_client()
    response = client.get("/dashboard", headers=auth_headers)
    assert response.status_code == 200
    assert b"LINE AI Secretary" in response.data
    assert b"dashboard.js" in response.data
    assert b"dashboard.css" in response.data
    assert b"AI Control Tower" in response.data


def test_dashboard_notes_api_success(auth_headers):
    client = app.test_client()
    mock_mcp_response = '[{"id": 1, "title": "テストノート", "body": "これはテストです", "category": "予定"}]'
    with patch("routes.dashboard.call_mcp_tool", return_value=mock_mcp_response) as mock_call:
        response = client.get("/api/dashboard/notes?user_id=test-user", headers=auth_headers)
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert len(data["notes"]) == 1
    assert data["notes"][0]["title"] == "テストノート"
    assert data["user_id"] == TEST_USER_ID
    mock_call.assert_called_once_with("list_notes", {"user_id": TEST_USER_ID})


def test_dashboard_system_exposes_four_feature_readiness(auth_headers):
    client = app.test_client()
    with patch("routes.dashboard.call_mcp_tool", return_value="[]"):
        response = client.get("/api/dashboard/system", headers=auth_headers)
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    features = data["features"]
    assert features["english_learning"]["status"] == "online"
    assert "MVP" in features["english_learning"]["detail"]
    assert features["stocks"]["status"] == "planned"
    assert features["ai_news"]["status"] == "planned"
    assert features["voice"]["status"] == "online"


def test_dashboard_oracle_n8n_status_handles_missing_payload():
    assert _get_oracle_n8n_status(None) == ""
    assert _get_oracle_n8n_status({}) == ""
    assert _get_oracle_n8n_status({"docker": None}) == ""
    assert _get_oracle_n8n_status({"docker": {"n8n": None}}) == ""
    assert _get_oracle_n8n_status({"docker": {"n8n": {"status": "RUNNING"}}}) == "running"


def test_dashboard_notes_api_user_id_resolution_from_db(auth_headers, monkeypatch):
    monkeypatch.delenv("DASHBOARD_OWNER_USER_ID", raising=False)
    init_db()
    save_message("db-active-user", "user", "こんにちは")
    client = app.test_client()
    with patch("routes.dashboard.call_mcp_tool", return_value="[]") as mock_call:
        response = client.get("/api/dashboard/notes", headers=auth_headers)
    assert response.status_code == 400
    data = response.get_json()
    assert data["ok"] is False
    assert data["error"] == "user_id is required"
    mock_call.assert_not_called()


def test_dashboard_notes_api_error_handling(auth_headers):
    client = app.test_client()
    with patch("routes.dashboard.call_mcp_tool", side_effect=RuntimeError("MCP server is down")):
        response = client.get("/api/dashboard/notes?user_id=test-user", headers=auth_headers)
    assert response.status_code == 500
    data = response.get_json()
    assert data["ok"] is False
    assert data["error"] == "internal server error"
    assert data["user_id"] == TEST_USER_ID


def test_add_note_success(auth_headers):
    client = app.test_client()
    payload = {"user_id": "test-user", "title": "テストタイトル", "body": "テスト本文", "category": "技術"}
    with patch("routes.dashboard.call_mcp_tool", return_value="saved") as mock_call:
        response = client.post("/api/dashboard/notes", json=payload, headers=auth_headers)
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["result"] == "saved"
    assert data["user_id"] == TEST_USER_ID
    mock_call.assert_called_once_with("save_note", {"user_id": TEST_USER_ID, "title": "テストタイトル", "body": "テスト本文", "category": "技術"})


def test_add_note_validation_error(auth_headers):
    client = app.test_client()
    response = client.post("/api/dashboard/notes?user_id=test-user", json={"title": "", "body": "本文"}, headers=auth_headers)
    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    assert "Title is required" in response.get_json()["error"]
    response = client.post("/api/dashboard/notes?user_id=test-user", json={"title": "タイトル", "body": "  "}, headers=auth_headers)
    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    assert "Body is required" in response.get_json()["error"]


def test_delete_note_success(auth_headers):
    client = app.test_client()
    with patch("routes.dashboard.call_mcp_tool", return_value="deleted") as mock_call:
        response = client.delete("/api/dashboard/notes/123?user_id=test-user", headers=auth_headers)
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["result"] == "deleted"
    assert data["user_id"] == TEST_USER_ID
    mock_call.assert_called_once_with("delete_note", {"user_id": TEST_USER_ID, "id": "123"})


def test_mcp_error_during_crud(auth_headers):
    client = app.test_client()
    with patch("routes.dashboard.call_mcp_tool", side_effect=RuntimeError("MCP save failed")):
        response = client.post("/api/dashboard/notes?user_id=test-user", json={"title": "T", "body": "B"}, headers=auth_headers)
    assert response.status_code == 500
    assert response.get_json()["ok"] is False
    assert response.get_json()["error"] == "internal server error"
    with patch("routes.dashboard.call_mcp_tool", side_effect=RuntimeError("MCP delete failed")):
        response = client.delete("/api/dashboard/notes/999?user_id=test-user", headers=auth_headers)
    assert response.status_code == 500
    assert response.get_json()["ok"] is False
    assert response.get_json()["error"] == "internal server error"
