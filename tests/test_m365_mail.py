"""Tests for the opt-in Microsoft Graph mail webhook."""
from flask import Flask

import m365_mail


def _client():
    app = Flask(__name__)
    m365_mail.register_m365_mail_route(app)
    return app.test_client()


def test_graph_validation_token_is_returned_as_plain_text_for_get():
    response = _client().get("/m365/notifications?validationToken=verify-me")
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "verify-me"
    assert response.mimetype == "text/plain"


def test_graph_validation_token_is_returned_for_post_too():
    response = _client().post("/m365/notifications?validationToken=verify-me")
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "verify-me"
    assert response.mimetype == "text/plain"


def test_graph_validation_token_length_is_bounded():
    response = _client().get("/m365/notifications?validationToken=" + ("x" * 2049))
    assert response.status_code == 400


def test_mail_intake_fails_closed_when_not_configured(monkeypatch):
    for key in (
        "M365_TENANT_ID",
        "M365_CLIENT_ID",
        "M365_CLIENT_SECRET",
        "M365_MAILBOX_USER",
        "M365_WEBHOOK_CLIENT_STATE",
        "EMAIL_ALLOWED_SENDERS",
    ):
        monkeypatch.delenv(key, raising=False)
    response = _client().post("/m365/notifications", json={"value": []})
    assert response.status_code == 503
    assert response.get_json()["ok"] is False


def test_invalid_notification_payload_is_rejected_when_configured(monkeypatch):
    monkeypatch.setenv("M365_TENANT_ID", "tenant")
    monkeypatch.setenv("M365_CLIENT_ID", "client")
    monkeypatch.setenv("M365_CLIENT_SECRET", "secret")
    monkeypatch.setenv("M365_MAILBOX_USER", "mailbox@example.com")
    monkeypatch.setenv("M365_WEBHOOK_CLIENT_STATE", "long-random-state")
    monkeypatch.setenv("EMAIL_ALLOWED_SENDERS", "owner@example.com")
    response = _client().post("/m365/notifications", json={"notValue": []})
    assert response.status_code == 400
    assert response.get_json()["ok"] is False



def test_html_email_body_extracts_visible_text_but_ignores_script():
    text = m365_mail._plain_body(
        {
            "body": {
                "contentType": "html",
                "content": "<html><body><p>分散Loopを1回、安全確認付きで実行</p><script>分散Loop開始</script></body></html>",
            }
        }
    )
    assert text == "分散Loopを1回、安全確認付きで実行"
