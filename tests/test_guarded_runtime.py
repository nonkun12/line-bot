from types import SimpleNamespace

import scripts.run_guarded_runtime as guarded_runtime


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=self.responses.pop(0))
            )]
        )


def test_guarded_ask_uses_bounded_json_completion_and_low_reasoning():
    completions = FakeCompletions(['{"file":"app.py"}'])
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )

    result = guarded_runtime.guarded_ask(client, "json only", "pick a file")

    assert result == '{"file":"app.py"}'
    kwargs = completions.calls[0]
    assert kwargs["max_completion_tokens"] == guarded_runtime.MAX_COMPLETION_TOKENS
    assert kwargs["reasoning_effort"] == "low"
    assert kwargs["include_reasoning"] is False
    assert kwargs["response_format"] == {"type": "json_object"}


def test_guarded_ask_accepts_legacy_max_tokens_keyword():
    completions = FakeCompletions(['{"file":"app.py"}'])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    guarded_runtime.guarded_ask(client, "json only", "pick a file", max_tokens=900)

    assert completions.calls[0]["max_completion_tokens"] == 900


def test_guarded_ask_retries_empty_output_with_compact_json_instruction():
    completions = FakeCompletions(["", '{"file":null}'])
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )

    result = guarded_runtime.guarded_ask(client, "json only", "pick a file")

    assert result == '{"file":null}'
    assert len(completions.calls) == 2
    assert "compact valid JSON object only" in completions.calls[1]["messages"][0]["content"]



def test_guarded_ask_accepts_large_japanese_plan_payload_without_local_truncation():
    old = "古い実装文字列" * 170
    new = "新しい実装文字列" * 300
    payload = '{"file":"app.py","changes":[{"file":"app.py","old":' + __import__("json").dumps(old, ensure_ascii=False) + ',"new":' + __import__("json").dumps(new, ensure_ascii=False) + "}]}"
    completions = FakeCompletions([payload])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = guarded_runtime.guarded_ask(client, "json only", "build a plan")

    assert result == payload
    assert len(old) == 1020
    assert len(new) == 2100
    assert completions.calls[0]["max_completion_tokens"] == guarded_runtime.MAX_COMPLETION_TOKENS
