from types import SimpleNamespace

from core.rsi_rea_lfm3_shadow import (
    assess_rsi_request,
    rea_shadow_gate,
    _strict_json_object,
    safety_state_allows_inference,
)


class FakeCompletions:
    def __init__(self, content):
        self.content = content
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content=self.content))
        ])


class FakeClient:
    def __init__(self, content):
        self.completions = FakeCompletions(content)
        self.chat = SimpleNamespace(completions=self.completions)


def valid(**overrides):
    value = {
        "intent": "rsi_self_improvement_experiment",
        "risk": "LOW",
        "requires_human_approval": True,
        "reason": "RSI software self-improvement request",
    }
    value.update(overrides)
    import json
    return json.dumps(value)


def test_lfm3_structured_output_is_sent_to_local_client():
    client = FakeClient(valid())
    result = assess_rsi_request(
        client, model="lfm3:1.7b-qad-q4_0",
        request_text="RSIの自己改善実験",
        stop_state="INACTIVE", global_hold_state="CLEAR",
    )
    assert result["gate"] == "REVIEW_ONLY"
    assert result["mode"] == "SHADOW_ONLY"
    assert result["execution_authorized"] is False
    assert client.completions.kwargs["response_format"]["type"] == "json_schema"


def test_financial_rsi_misclassification_is_held():
    client = FakeClient(valid(intent="unknown"))
    result = assess_rsi_request(
        client, model="lfm3", request_text="RSI experiment",
        stop_state="INACTIVE", global_hold_state="CLEAR",
    )
    assert result["gate"] == "HOLD"


def test_model_cannot_self_approve():
    client = FakeClient(valid(requires_human_approval=False))
    result = assess_rsi_request(
        client, model="lfm3", request_text="RSI experiment",
        stop_state="INACTIVE", global_hold_state="CLEAR",
    )
    assert result["gate"] == "BLOCKED"
    assert result["reason_code"] == "model_attempted_approval_bypass"


def test_prose_or_duplicate_json_is_blocked():
    for raw in (
        "Here is JSON: " + valid(),
        '{"intent":"unknown","intent":"unknown","risk":"LOW",'
        '"requires_human_approval":true,"reason":"x"}',
    ):
        try:
            _strict_json_object(raw)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid model output was accepted")


def test_stop_and_global_hold_fail_closed():
    classification = {
        "intent": "rsi_self_improvement_experiment",
        "risk": "LOW",
        "requires_human_approval": True,
        "reason": "test",
    }
    assert rea_shadow_gate(
        classification, stop_state="ACTIVE", global_hold_state="CLEAR"
    )["gate"] == "BLOCKED"
    assert rea_shadow_gate(
        classification, stop_state="INACTIVE", global_hold_state="UNKNOWN"
    )["gate"] == "BLOCKED"


def test_model_transport_failure_is_blocked():
    result = assess_rsi_request(
        FakeClient("not json"), model="lfm3",
        request_text="RSI experiment",
        stop_state="INACTIVE", global_hold_state="CLEAR",
    )
    assert result["gate"] == "BLOCKED"
    assert result["execution_authorized"] is False



def test_unknown_or_active_safety_state_prevents_model_inference():
    assert safety_state_allows_inference("INACTIVE", "CLEAR") is True
    assert safety_state_allows_inference("ACTIVE", "CLEAR") is False
    assert safety_state_allows_inference("UNKNOWN", "CLEAR") is False
    assert safety_state_allows_inference("INACTIVE", "ACTIVE") is False
    assert safety_state_allows_inference("INACTIVE", "UNKNOWN") is False
