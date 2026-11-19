"""n8n_delegate._delegate_to_n8n() の単体テスト。

- 送信ペイロードが user_id / message の2項目のみであること
- httpx.postが例外を送出しても呼び出し元に伝播しない(fire-and-forget)こと
"""
import httpx
import pytest

from n8n_delegate import _delegate_to_n8n


def test_delegate_to_n8n_posts_expected_payload(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout

        class _Resp:
            status_code = 200

        return _Resp()

    monkeypatch.setattr(httpx, "post", fake_post)

    _delegate_to_n8n("user-123", "こんにちは", "https://example.com/webhook/line-in")

    assert captured["url"] == "https://example.com/webhook/line-in"
    assert captured["json"] == {"user_id": "user-123", "message": "こんにちは"}
    # reply_tokenが含まれていないこと(2項目のみ)
    assert set(captured["json"].keys()) == {"user_id", "message"}


def test_delegate_to_n8n_swallows_exception(monkeypatch):
    def failing_post(url, json=None, timeout=None):
        raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(httpx, "post", failing_post)

    # 例外が外に伝播しないこと
    _delegate_to_n8n("user-456", "テスト", "https://example.com/webhook/line-in")


def test_delegate_to_n8n_uses_custom_timeout(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["timeout"] = timeout

        class _Resp:
            status_code = 200

        return _Resp()

    monkeypatch.setattr(httpx, "post", fake_post)

    _delegate_to_n8n("user-789", "テスト", "https://example.com/webhook/line-in", timeout=10)

    assert captured["timeout"] == 10
