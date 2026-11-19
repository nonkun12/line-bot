import os
from unittest.mock import Mock, patch

import pytest

from gemini_n8n_client import GeminiN8nError, call_gemini_via_n8n


def _response(status_code=200, payload=None):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload or {
        "request_id": "req-1",
        "provider": "gemini",
        "model": "gemini-2.5-flash",
        "reply": "こんにちは！",
    }
    return response


def test_call_gemini_via_n8n_sends_expected_payload_and_headers():
    with patch.dict(
        os.environ,
        {
            "GEMINI_N8N_WEBHOOK_URL": "https://example.test/webhook/gemini",
            "GEMINI_N8N_INTERNAL_KEY": "secret",
        },
        clear=False,
    ), patch("gemini_n8n_client.httpx.post", return_value=_response()) as post:
        result = call_gemini_via_n8n("こんにちは", "U123", "req-1")

    assert result["reply"] == "こんにちは！"
    post.assert_called_once_with(
        "https://example.test/webhook/gemini",
        json={
            "request_id": "req-1",
            "user_id": "U123",
            "message": "こんにちは",
        },
        headers={
            "Content-Type": "application/json",
            "X-Internal-Key": "secret",
        },
        timeout=10.0,
    )


def test_call_gemini_via_n8n_requires_webhook_url():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(GeminiN8nError, match="WEBHOOK_URL"):
            call_gemini_via_n8n("hello", "U1", "req-1")


def test_call_gemini_via_n8n_requires_internal_key():
    with patch.dict(
        os.environ,
        {"GEMINI_N8N_WEBHOOK_URL": "https://example.test/webhook/gemini"},
        clear=True,
    ):
        with pytest.raises(GeminiN8nError, match="INTERNAL_KEY"):
            call_gemini_via_n8n("hello", "U1", "req-1")


def test_call_gemini_via_n8n_rejects_non_200():
    with patch.dict(
        os.environ,
        {
            "GEMINI_N8N_WEBHOOK_URL": "https://example.test/webhook/gemini",
            "GEMINI_N8N_INTERNAL_KEY": "secret",
        },
        clear=False,
    ), patch(
        "gemini_n8n_client.httpx.post",
        return_value=_response(500, {"error": "temporary"}),
    ):
        with pytest.raises(GeminiN8nError, match="HTTP 500"):
            call_gemini_via_n8n("hello", "U1", "req-1")


def test_call_gemini_via_n8n_rejects_empty_reply():
    with patch.dict(
        os.environ,
        {
            "GEMINI_N8N_WEBHOOK_URL": "https://example.test/webhook/gemini",
            "GEMINI_N8N_INTERNAL_KEY": "secret",
        },
        clear=False,
    ), patch(
        "gemini_n8n_client.httpx.post",
        return_value=_response(200, {"reply": ""}),
    ):
        with pytest.raises(GeminiN8nError, match="empty reply"):
            call_gemini_via_n8n("hello", "U1", "req-1")
