from core.self_introduction import build_self_introduction, is_self_introduction_request


def test_explicit_all_ai_introduction_is_detected():
    assert is_self_introduction_request("各AI、自己紹介して")


def test_non_plural_self_introduction_is_not_intercepted():
    assert not is_self_introduction_request("自己紹介して")


def test_introduction_uses_registry_agents():
    text = build_self_introduction()
    assert "【AI役割分担】" in text
    assert "■ 登録済み専門AI" in text
    assert "Management AI" in text
    assert "※専門AIの一覧・説明はAgent Registryから動的に取得します。" in text
