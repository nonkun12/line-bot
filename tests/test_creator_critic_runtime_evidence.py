from __future__ import annotations

from scripts.run_creator_critic_github import run_discussion


def test_creator_critic_records_runtime_metrics_without_claiming_effectiveness():
    calls = []

    def generate(messages, max_tokens):
        calls.append((messages, max_tokens))
        return "A bounded proposal." if messages[0]["content"].startswith("You are Creator") else "Missing evidence; HOLD."

    report = run_discussion(
        generate,
        "Observed failure: <untrusted_loop_observation>status=FAIL</untrusted_loop_observation>",
        rounds=1,
    )

    assert report["status"] == "DISCUSSION_ONLY"
    assert report["evidence_status"] == "RUNTIME_MEASURED"
    assert report["improvement_effectiveness"] == "NOT_MEASURED"
    metrics = report["execution_metrics"]
    assert metrics["turn_count"] == 2
    assert metrics["non_empty_turn_count"] == 2
    assert metrics["elapsed_seconds"] >= 0
    assert metrics["objective_source"] == "loop_failure_observation"
    assert [turn["role"] for turn in metrics["turns"]] == ["creator", "critic"]
    assert all(turn["elapsed_seconds"] >= 0 and turn["non_empty"] for turn in metrics["turns"])
    assert len(calls) == 2


def test_creator_critic_marks_default_objective_source():
    report = run_discussion(
        lambda messages, max_tokens: "Review proposal; REVIEW.",
        "A generic objective.",
        rounds=1,
    )

    assert report["execution_metrics"]["objective_source"] == "manual_or_default"
    assert report["improvement_effectiveness"] == "NOT_MEASURED"


def test_creator_critic_invalid_rounds_raises_value_error_and_no_generate_call():
    calls = []

    def generate(messages, max_tokens):
        calls.append((messages, max_tokens))
        return "Should not be called"

    import pytest
    with pytest.raises(ValueError, match="rounds must be between 1 and 3"):
        run_discussion(generate, "Some objective", rounds=0)

    assert len(calls) == 0
