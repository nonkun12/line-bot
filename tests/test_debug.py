import asyncio

import pytest
from fastapi.testclient import TestClient

from mini_debug_app.main import app
from mini_debug_app.service import debug_error


client = TestClient(app)


def test_analyze_error():

    response = client.post(
        "/debug/",
        json={
            "error_content": """
Traceback (most recent call last):
ZeroDivisionError: division by zero
"""
        }
    )

    assert response.status_code == 200

    result = response.json()["error_analysis"]

    assert "error_info" in result
    assert "analysis" in result
    assert "fix_suggestion" in result


# =========================================================
# 空/不正入力
# =========================================================
def test_empty_error_content_is_rejected():
    response = client.post(
        "/debug/",
        json={"error_content": ""}
    )

    # ErrorInputのvalidatorで拒否されるため、FastAPI/pydanticの
    # バリデーションエラー(422)になる。500(サーバー内部エラー)とは区別する。
    assert response.status_code == 422


def test_whitespace_only_error_content_is_rejected():
    response = client.post(
        "/debug/",
        json={"error_content": "   \n\t  "}
    )

    assert response.status_code == 422


def test_missing_error_content_field_is_rejected():
    response = client.post(
        "/debug/",
        json={}
    )

    assert response.status_code == 422


# =========================================================
# analyzer / fixer 内部エラー
# =========================================================
def test_analyzer_error_returns_500(monkeypatch):
    def raise_analyzer_error(_error_info):
        raise ValueError("analyzer boom")

    monkeypatch.setattr(
        "mini_debug_app.service.analyze_error",
        raise_analyzer_error,
    )

    response = client.post(
        "/debug/",
        json={"error_content": "TypeError: something went wrong"}
    )

    assert response.status_code == 500
    assert "error analysis failed" in response.json()["detail"]


def test_fixer_error_returns_500(monkeypatch):
    def raise_fixer_error(_error_info):
        raise ValueError("fixer boom")

    monkeypatch.setattr(
        "mini_debug_app.service.generate_fix_suggestion",
        raise_fixer_error,
    )

    response = client.post(
        "/debug/",
        json={"error_content": "TypeError: something went wrong"}
    )

    assert response.status_code == 500
    assert "fix suggestion generation failed" in response.json()["detail"]


def test_collector_error_returns_500(monkeypatch):
    def raise_collector_error(_error_content):
        raise ValueError("collector boom")

    monkeypatch.setattr(
        "mini_debug_app.service.collect_error",
        raise_collector_error,
    )

    response = client.post(
        "/debug/",
        json={"error_content": "TypeError: something went wrong"}
    )

    assert response.status_code == 500
    assert "error collection failed" in response.json()["detail"]


# =========================================================
# service層の単体テスト (FastAPIを経由しない)
# =========================================================
def test_service_debug_error_returns_structured_result():
    result = asyncio.run(
        debug_error(
            "Traceback (most recent call last):\n"
            '  File "app.py", line 10\n'
            "KeyError: 'user_id'"
        )
    )

    assert result["error_info"]["error_type"] == "KeyError"
    assert result["error_info"]["key"] == "user_id"
    assert "analysis" in result
    assert "fix_suggestion" in result


def test_service_debug_error_without_traceback_still_returns_result():
    result = asyncio.run(
        debug_error("よくわからないエラーが出た")
    )

    assert result["error_info"]["has_traceback"] is False
    assert "analysis" in result
    assert "fix_suggestion" in result


def test_service_debug_error_wraps_analyzer_exception(monkeypatch):
    def raise_analyzer_error(_error_info):
        raise ValueError("boom")

    monkeypatch.setattr(
        "mini_debug_app.service.analyze_error",
        raise_analyzer_error,
    )

    with pytest.raises(RuntimeError, match="error analysis failed"):
        asyncio.run(debug_error("TypeError: boom"))
