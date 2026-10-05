from distributed_loop_trigger import request_distributed_loop

def test_trigger_ignores_non_command(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")
    handled, reply = request_distributed_loop("u1", "こんにちは")
    assert handled is False
    assert reply == ""

def test_trigger_recognizes_loop_command_aliases(monkeypatch):\n    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "u1")\n    monkeypatch.delenv("GITHUB_ACTIONS_DISPATCH_TOKEN", raising=False)\n    monkeypatch.delenv("GITHUB_TOKEN", raising=False)\n    for command in ("分散ループ開始", "分散Loop開始", "分散AIループ開始", "分散AI Loop開始"):\n        handled, reply = request_distributed_loop("u1", command)\n        assert handled is True\n        assert "認証未設定" in reply\n\n\ndef test_trigger_denies_unknown_user(monkeypatch):
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
