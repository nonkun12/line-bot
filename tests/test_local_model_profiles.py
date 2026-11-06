import json

import pytest

import core.local_model_profiles as profiles
from core.local_model_profiles import LocalModelProfile, load_local_model_profile, local_model_call


def test_loads_bonsai_and_lfm_as_independent_explicit_profiles():
    env = {
        "CREATOR_CRITIC_BONSAI_BASE_URL": "http://127.0.0.1:8081/v1",
        "CREATOR_CRITIC_BONSAI_MODEL": "bonsai-test",
        "CREATOR_CRITIC_LFM_BASE_URL": "http://localhost:8082/v1",
        "CREATOR_CRITIC_LFM_MODEL": "LiquidAI/LFM3-1.7B",
    }
    bonsai = load_local_model_profile("bonsai", env)
    lfm = load_local_model_profile("lfm", env)

    assert (bonsai.base_url, bonsai.model) == ("http://127.0.0.1:8081/v1", "bonsai-test")
    assert (lfm.base_url, lfm.model) == ("http://localhost:8082/v1", "LiquidAI/LFM3-1.7B")


@pytest.mark.parametrize("url", [
    "https://example.com/v1",
    "http://example.com/v1",
    "http://127.0.0.1:8081/v1?token=x",
    "http://user:pass@127.0.0.1:8081/v1",
    "http://127.0.0.1:8081/v1#fragment",
])
def test_rejects_non_loopback_or_ambiguous_endpoints(url):
    with pytest.raises(ValueError):
        profiles._validate_loopback_url(url)


def test_missing_lfm_endpoint_or_model_fails_closed():
    with pytest.raises(RuntimeError, match="CREATOR_CRITIC_LFM_BASE_URL"):
        load_local_model_profile("lfm", {"CREATOR_CRITIC_LFM_MODEL": "LiquidAI/LFM3-1.7B"})


def test_local_call_uses_profile_model_and_rejects_redirects(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, size=-1):
            captured["read_limit"] = size
            return json.dumps({"choices": [{"message": {"content": "local response"}}]}).encode()

    class FakeOpener:
        def open(self, request, timeout):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode())
            captured["timeout"] = timeout
            return FakeResponse()

    def fake_build_opener(handler):
        assert handler is profiles._RejectRedirects
        return FakeOpener()

    monkeypatch.setattr(profiles, "build_opener", fake_build_opener)
    profile = LocalModelProfile("lfm", "http://127.0.0.1:8082/v1", "LiquidAI/LFM3-1.7B")
    assert local_model_call("hello", profile) == "local response"
    assert captured["url"] == "http://127.0.0.1:8082/v1/chat/completions"
    assert captured["body"]["model"] == "LiquidAI/LFM3-1.7B"
    assert captured["timeout"] == 30.0
    assert captured["read_limit"] == profiles.MAX_RESPONSE_BYTES + 1


def test_profile_rejects_invalid_timeout():
    with pytest.raises(ValueError, match="between 1 and 120"):
        load_local_model_profile("bonsai", {
            "CREATOR_CRITIC_BONSAI_BASE_URL": "http://127.0.0.1:8081/v1",
            "CREATOR_CRITIC_BONSAI_MODEL": "bonsai-test",
            "CREATOR_CRITIC_BONSAI_TIMEOUT": "999",
        })


def test_local_call_rejects_oversized_prompt_before_network(monkeypatch):
    def unexpected_network_call(*_args, **_kwargs):
        pytest.fail("network must not be called for an oversized prompt")

    monkeypatch.setattr(profiles, "build_opener", unexpected_network_call)
    profile = LocalModelProfile("lfm", "http://127.0.0.1:8082/v1", "lfm-test")
    with pytest.raises(ValueError, match="exceeds"):
        local_model_call("x" * (profiles.MAX_PROMPT_CHARS + 1), profile)


def test_local_call_rejects_oversized_response(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, size=-1):
            assert size == profiles.MAX_RESPONSE_BYTES + 1
            return b"x" * size

    class FakeOpener:
        def open(self, _request, timeout):
            return FakeResponse()

    monkeypatch.setattr(profiles, "build_opener", lambda _handler: FakeOpener())
    profile = LocalModelProfile("lfm", "http://127.0.0.1:8082/v1", "lfm-test")
    with pytest.raises(RuntimeError, match="exceeds size limit"):
        local_model_call("hello", profile)
