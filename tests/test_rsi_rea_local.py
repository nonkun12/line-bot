import pytest

from core.rsi_rea_local import build_loopback_rea_agents


def test_loopback_rea_factory_builds_separate_local_roles():
    agents = build_loopback_rea_agents(
        creator_model="bonsai-local:9b",
        critic_model="lfm3:1.7b-qad-q4_0",
    )
    assert agents.creator_model == "bonsai-local:9b"
    assert agents.critic_model == "lfm3:1.7b-qad-q4_0"
    assert agents.creator._model is not agents.critic._model


def test_loopback_rea_factory_rejects_same_model_identity():
    with pytest.raises(ValueError, match="distinct local model identities"):
        build_loopback_rea_agents(
            creator_model="lfm3:1.7b-qad-q4_0",
            critic_model="lfm3:1.7b-qad-q4_0",
        )


def test_loopback_rea_factory_never_accepts_remote_endpoint_configuration():
    # The factory intentionally exposes model names only, not arbitrary URLs.
    with pytest.raises(TypeError):
        build_loopback_rea_agents(
            creator_model="creator",
            critic_model="critic",
            base_url="https://provider.example",
        )
