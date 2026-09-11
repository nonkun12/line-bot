from app_development import dispatch_app_development_workflow


class FakeResponse:
    status_code = 204


def test_unauthorized_user_is_rejected_before_dispatch(monkeypatch):
    def fail_post(*args, **kwargs):
        raise AssertionError("HTTP dispatch must not be attempted")

    monkeypatch.delenv("DEV_ALLOWED_USER_IDS", raising=False)
    monkeypatch.setattr("app_development.httpx.post", fail_post)

    reply = dispatch_app_development_workflow(
        "小さなTODOアプリを作って",
        user_id="U-not-allowed",
        token="secret",
    )

    assert "権限がありません" in reply


def test_authorized_user_dispatches_expected_workflow(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        captured["headers"] = kwargs["headers"]
        return FakeResponse()

    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U123,U456")
    monkeypatch.setattr("app_development.httpx.post", fake_post)

    reply = dispatch_app_development_workflow(
        "小さなTODOアプリを作って",
        user_id="U123",
        token="secret",
    )

    assert "/actions/workflows/app-development.yml/dispatches" in captured["url"]
    assert captured["json"] == {
        "ref": "main",
        "inputs": {
            "requirement": "小さなTODOアプリを作って",
            "user_id": "U123",
        },
    }
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert "開始しました" in reply
