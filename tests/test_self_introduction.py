from types import SimpleNamespace

import core.self_introduction as self_introduction


def test_explicit_all_ai_introduction_is_detected():
    assert self_introduction.is_self_introduction_request("各AI、自己紹介して")


def test_non_plural_self_introduction_is_not_intercepted():
    assert not self_introduction.is_self_introduction_request("自己紹介して")


def test_role_variants_are_detected():
    assert self_introduction.is_self_introduction_request("各AIの役割を教えて")
    assert self_introduction.is_self_introduction_request("全エージェント、担当を紹介して")


def test_introduction_uses_registry_agents(monkeypatch):
    fake_agent = SimpleNamespace(
        name="test-specialist",
        description="テスト用専門AI",
        enabled=True,
    )
    class FakeRegistry:
        def names(self):
            return ["test-specialist"]
        def get(self, name):
            assert name == "test-specialist"
            return fake_agent

    monkeypatch.setattr(
        self_introduction,
        "build_core_agent_registry",
        lambda: FakeRegistry(),
    )
    text = self_introduction.build_self_introduction()
    assert "【AI役割分担】" in text
    assert "■ 登録済み専門AI" in text
    assert "test-specialist: テスト用専門AI [稼働]" in text
    assert "※専門AIの一覧・説明はAgent Registryから動的に取得します。" in text
