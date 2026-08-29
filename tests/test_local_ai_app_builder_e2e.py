"""Local, Render-free E2E contract test for line-bot -> ai-app-builder.

Run locally with:
    AI_APP_BUILDER_LOCAL_PATH=/path/to/ai-app-builder pytest -q tests/test_local_ai_app_builder_e2e.py

The test imports the real ai-app-builder FastAPI application and the real
line-bot delegation function, but replaces the Graph execution and LINE push
with deterministic test doubles. No Render, Groq, LINE API, or external HTTP
service is contacted.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient


LOCAL_APP_BUILDER_PATH = os.environ.get("AI_APP_BUILDER_LOCAL_PATH", "").strip()

pytestmark = pytest.mark.skipif(
    not LOCAL_APP_BUILDER_PATH,
    reason="AI_APP_BUILDER_LOCAL_PATH is required for the local cross-repo E2E test",
)


def _load_builder_module():
    path = str(Path(LOCAL_APP_BUILDER_PATH).expanduser().resolve())
    if path not in sys.path:
        sys.path.insert(0, path)
    return importlib.import_module("interface.n8n_webhook")


def test_line_bot_delegation_reaches_real_ai_app_builder_app(monkeypatch):
    """Exercise the real line-bot delegate and real ai-app-builder FastAPI app."""
    builder = _load_builder_module()
    import n8n_delegate

    captured = {}

    def fake_graph(initial_state, timeout):
        captured["graph_input"] = initial_state
        captured["graph_timeout"] = timeout
        return True, {
            **initial_state,
            "project_name": None,
            "project_path": None,
            "test_result": {"passed": True},
            "final_reply": "ローカルE2E成功",
            "agent_results": {},
        }

    monkeypatch.setattr(builder, "invoke_graph_with_timeout", fake_graph)
    client = TestClient(builder.app)

    def local_http_post(url, **kwargs):
        captured["url"] = url
        captured["request_kwargs"] = kwargs
        response = client.post(
            "/interface/generate",
            json=kwargs["json"],
            headers=kwargs.get("headers"),
        )

        class ResponseAdapter:
            status_code = response.status_code

            def json(self):
                return response.json()

        return ResponseAdapter()

    pushed = {}
    monkeypatch.setattr(n8n_delegate, "httpx_post", local_http_post, raising=False)
    monkeypatch.setattr(n8n_delegate.httpx, "post", local_http_post)
    monkeypatch.setattr(n8n_delegate, "AI_APP_BUILDER_URL", "http://local-ai-app-builder")
    monkeypatch.setattr(n8n_delegate, "AI_APP_BUILDER_SHARED_SECRET", "")
    monkeypatch.setattr(n8n_delegate, "AI_APP_BUILDER_TIMEOUT_SECONDS", 30.0)
    monkeypatch.setattr(n8n_delegate, "record_step", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        n8n_delegate,
        "_push_line_reply",
        lambda user_id, text: pushed.update(user_id=user_id, text=text),
    )

    n8n_delegate._delegate_to_n8n(
        "U_LOCAL_E2E",
        "Todoアプリを作って",
        "http://unused-n8n-webhook",
    )

    assert captured["url"] == "http://local-ai-app-builder/interface/generate"
    assert captured["request_kwargs"]["json"] == {
        "user_id": "U_LOCAL_E2E",
        "message": "Todoアプリを作って",
    }
    assert captured["graph_input"]["user_id"] == "U_LOCAL_E2E"
    assert captured["graph_input"]["raw_message"] == "Todoアプリを作って"
    assert pushed == {
        "user_id": "U_LOCAL_E2E",
        "text": "ローカルE2E成功",
    }


def test_real_ai_app_builder_endpoint_keeps_shared_secret_contract(monkeypatch):
    """Verify the real builder endpoint accepts the expected secret when configured."""
    builder = _load_builder_module()
    client = TestClient(builder.app)

    monkeypatch.setattr(builder, "N8N_WEBHOOK_SHARED_SECRET", "local-secret")
    monkeypatch.setattr(
        builder,
        "invoke_graph_with_timeout",
        lambda initial_state, timeout: (
            True,
            {
                **initial_state,
                "project_name": None,
                "project_path": None,
                "test_result": {"passed": True},
                "final_reply": "secret contract ok",
                "agent_results": {},
            },
        ),
    )

    unauthorized = client.post(
        "/interface/generate",
        json={"user_id": "U1", "message": "Todoアプリを作って"},
    )
    assert unauthorized.status_code == 401

    authorized = client.post(
        "/interface/generate",
        json={"user_id": "U1", "message": "Todoアプリを作って"},
        headers={"x-shared-secret": "local-secret"},
    )
    assert authorized.status_code == 200
    assert authorized.json()["status"] == "success"
    assert authorized.json()["summary"] == "secret contract ok"
