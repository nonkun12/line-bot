from distributed_loop_trigger import request_distributed_loop

def test_trigger_ignores_non_command(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    handled, reply = request_distributed_loop("u1", "こんにちは")
    assert handled is False
    assert reply == ""

def test_trigger_recognizes_loop_command_aliases(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.delenv("GITHUB_ACTIONS_DISPATCH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    for command in ("分散ループ開始", "分散Loop開始", "分散AIループ開始", "分散AI Loop開始"):
        handled, reply = request_distributed_loop("u1", command)
        assert handled is True
        assert "認証未設定" in reply

def test_trigger_denies_unknown_user(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    handled, reply = request_distributed_loop("u2", "分散ループ開始")
    assert handled is True
    assert "許可されていません" in reply

def test_trigger_requires_token(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.delenv("GITHUB_ACTIONS_DISPATCH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    handled, reply = request_distributed_loop("u1", "分散ループ開始")
    assert handled is True
    assert "認証未設定" in reply

def test_bounded_loop_command_selects_requested_count(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    monkeypatch.delenv("GITHUB_ACTIONS_DISPATCH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    handled, reply = request_distributed_loop("u1", "分散ループを4回、安全確認付きで実行")
    assert handled is True
    assert "認証未設定" in reply

def test_bounded_loop_without_safety_confirmation_does_not_trigger(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    handled, reply = request_distributed_loop("u1", "分散ループを4回")
    assert handled is False
    assert reply == ""

def test_invalid_loop_count_does_not_trigger(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    handled, reply = request_distributed_loop("u1", "分散ループを5回、安全確認付きで実行")
    assert handled is False
    assert reply == ""
