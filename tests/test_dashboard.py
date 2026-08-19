import pytest

from unittest.mock import patch, MagicMock
import json
from app import app
from db import init_db, save_message

@pytest.fixture
def auth_headers(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER", "testuser")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "testpass")
    import base64
    token = base64.b64encode(b"testuser:testpass").decode()
    headers = {"Authorization": "Basic " + token}
    original_test_client = app.test_client
    def authenticated_test_client(*args, **kwargs):
        client = original_test_client(*args, **kwargs)
        client.environ_base["HTTP_AUTHORIZATION"] = headers["Authorization"]
        return client
    monkeypatch.setattr(app, "test_client", authenticated_test_client)
    return headers

def test_dashboard_page_status_code_and_content(auth_headers):
    """
    /dashboard への GET リクエストが 200 OK を返し、
    期待される HTML コンテンツが含まれていることを確認する。
    """
    # データベース初期化
    init_db()

    client = app.test_client()
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert b"LINE AI Secretary" in response.data
    assert b"dashboard.js" in response.data
    assert b"dashboard.css" in response.data

def test_dashboard_notes_api_success(auth_headers):
    """
    /api/dashboard/notes API が正常な JSON データを返し、
    MCP クライアントが正しく呼び出されていることを検証する。
    """
    client = app.test_client()

    # MCPサーバーが返却する生データを模したJSON文字列
    mock_mcp_response = (
        '[{"id": 1, "title": "テストノート", "body": "これはテストです", "category": "予定"}]'
    )

    with patch("routes.dashboard.call_mcp_tool", return_value=mock_mcp_response) as mock_call:
        response = client.get("/api/dashboard/notes?user_id=test-user")
        assert response.status_code == 200

        data = response.get_json()
        assert data["ok"] is True
        assert len(data["notes"]) == 1
        assert data["notes"][0]["title"] == "テストノート"
        assert data["notes"][0]["body"] == "これはテストです"
        assert data["notes"][0]["category"] == "予定"

        # test-user は U19391b0b93be2f4d94284361153919ce に解決されていることを確認
        assert data["user_id"] == "U19391b0b93be2f4d94284361153919ce"

        # call_mcp_tool が期待通りのパラメータで呼び出されていることを確認
        mock_call.assert_called_once_with(
            "search_notes",
            {
                "user_id": "U19391b0b93be2f4d94284361153919ce",
                "keyword": "",
            }
        )

def test_dashboard_notes_api_user_id_resolution_from_db(auth_headers):
    """
    クエリパラメータで user_id が指定されていない場合、
    DB から最新のアクティブユーザーIDを取得することを確認する。
    """
    init_db()

    # テスト用ユーザーからのダミーメッセージを保存してアクティブユーザーを作る
    save_message("db-active-user", "user", "こんにちは")

    client = app.test_client()
    mock_mcp_response = '[]'

    with patch("routes.dashboard.call_mcp_tool", return_value=mock_mcp_response) as mock_call:
        response = client.get("/api/dashboard/notes") # user_id パラメータなし
        assert response.status_code == 200

        data = response.get_json()
        assert data["ok"] is True
        assert data["user_id"] == "db-active-user"

        # call_mcp_tool が db-active-user で呼び出されていることを確認
        mock_call.assert_called_once_with(
            "search_notes",
            {
                "user_id": "db-active-user",
                "keyword": "",
            }
        )

def test_dashboard_notes_api_error_handling(auth_headers):
    """
    MCP 呼び出しが失敗した（例外が送出された）場合に、
    API が適切に 500 エラーとエラー内容を返すことを検証する。
    """
    client = app.test_client()

    with patch("routes.dashboard.call_mcp_tool", side_effect=RuntimeError("MCP server is down")):
        response = client.get("/api/dashboard/notes?user_id=test-user")
        assert response.status_code == 500

        data = response.get_json()
        assert data["ok"] is False
        assert "MCP server is down" in data["error"]

def test_add_note_success(auth_headers):
    """
    POST /api/dashboard/notes が正常に入力された場合、
    MCP の save_note ツールが正しく呼ばれ、メモが登録できることを検証する。
    """
    client = app.test_client()
    payload = {
        "user_id": "test-user",
        "title": "テストタイトル",
        "body": "テスト本文",
        "category": "技術"
    }

    with patch("routes.dashboard.call_mcp_tool", return_value="saved") as mock_call:
        response = client.post("/api/dashboard/notes", json=payload)
        assert response.status_code == 200

        data = response.get_json()
        assert data["ok"] is True
        assert data["result"] == "saved"
        assert data["user_id"] == "U19391b0b93be2f4d94284361153919ce"

        mock_call.assert_called_once_with(
            "save_note",
            {
                "user_id": "U19391b0b93be2f4d94284361153919ce",
                "title": "テストタイトル",
                "body": "テスト本文",
                "category": "技術"
            }
        )

def test_add_note_validation_error(auth_headers):
    """
    POST /api/dashboard/notes でタイトルまたは本文が欠落している場合、
    400 Bad Request になることを検証する。
    """
    client = app.test_client()

    # タイトル欠落
    response = client.post("/api/dashboard/notes", json={"title": "", "body": "本文"}, headers=auth_headers)
    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    assert "Title is required" in response.get_json()["error"]

    # 本文欠落
    response = client.post("/api/dashboard/notes", json={"title": "タイトル", "body": "  "}, headers=auth_headers)
    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    assert "Body is required" in response.get_json()["error"]

def test_delete_note_success(auth_headers):
    """
    DELETE /api/dashboard/notes/<note_id> が呼び出された場合、
    MCP の delete_note ツールが正しい引数で呼ばれることを検証する。
    """
    client = app.test_client()

    with patch("routes.dashboard.call_mcp_tool", return_value="deleted") as mock_call:
        response = client.delete("/api/dashboard/notes/123?user_id=test-user")
        assert response.status_code == 200

        data = response.get_json()
        assert data["ok"] is True
        assert data["result"] == "deleted"
        assert data["user_id"] == "U19391b0b93be2f4d94284361153919ce"

        mock_call.assert_called_once_with(
            "delete_note",
            {
                "user_id": "U19391b0b93be2f4d94284361153919ce",
                "id": "123"
            }
        )

def test_mcp_error_during_crud(auth_headers):
    """
    POST や DELETE 時、MCP 呼び出しが例外を投げた場合に
    500 Internal Server Error が適切に返されることを検証する。
    """
    client = app.test_client()

    # POSTエラー
    with patch("routes.dashboard.call_mcp_tool", side_effect=RuntimeError("MCP save failed")):
        response = client.post("/api/dashboard/notes", json={"title": "T", "body": "B"})
        assert response.status_code == 500
        assert response.get_json()["ok"] is False
        assert "MCP save failed" in response.get_json()["error"]

    # DELETEエラー
    with patch("routes.dashboard.call_mcp_tool", side_effect=RuntimeError("MCP delete failed")):
        response = client.delete("/api/dashboard/notes/999?user_id=test-user")
        assert response.status_code == 500
        assert response.get_json()["ok"] is False
        assert "MCP delete failed" in response.get_json()["error"]
