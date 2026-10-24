import json
from unittest.mock import patch

import pytest

from scripts.run_creator_critic_local import (
    OpenAICompatibleLocalModel,
    _load_evidence,
)


def test_evidence_requires_all_measured_metrics():
    with pytest.raises(Exception, match="missing required metrics"):
        _load_evidence('{"accuracy": 0.9}')


def test_evidence_rejects_out_of_range_values():
    with pytest.raises(Exception, match="safety"):
        _load_evidence(
            '{"accuracy":0.9,"stability":0.9,"efficiency":0.9,"safety":2}'
        )


def test_adapter_refuses_non_loopback_http_endpoint():
    with pytest.raises(ValueError, match="loopback"):
        OpenAICompatibleLocalModel("http://example.com/v1")


def test_adapter_discovers_model_and_calls_chat_completions():
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/models"):
            return FakeResponse({"data": [{"id": "bonsai-test"}]})
        return FakeResponse({"choices": [{"message": {"content": "independent review"}}]})

    model = OpenAICompatibleLocalModel("http://127.0.0.1:8081/v1")
    with patch("scripts.run_creator_critic_local.urllib.request.urlopen", side_effect=fake_urlopen):
        result = model("evaluate this proposal")

    assert result == "independent review"
    assert model.model == "bonsai-test"
    assert requests[0].full_url.endswith("/models")
    assert requests[1].full_url.endswith("/chat/completions")
    body = json.loads(requests[1].data.decode("utf-8"))
    assert body["model"] == "bonsai-test"
    assert body["messages"][0]["content"] == "evaluate this proposal"
    assert body["enable_thinking"] is False
