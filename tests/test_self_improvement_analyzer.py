from core.self_improvement import ImprovementSignal
from core.self_improvement_analyzer import analyze_signals


def test_analyzer_groups_recurring_failure_details():
    signals = (
        ImprovementSignal("failure", "task-1", "HTTP 500 at commit abcdef1234567890"),
        ImprovementSignal("repair", "task-2", "HTTP 500 at commit deadbeefcafebabe"),
        ImprovementSignal("failure", "task-3", "different failure"),
    )

    analysis = analyze_signals(signals)

    assert analysis.total_signals == 3
    assert analysis.failure_count == 2
    assert analysis.repair_count == 1
    assert len(analysis.recurring_patterns) == 1
    pattern = analysis.recurring_patterns[0]
    assert pattern.count == 2
    assert pattern.signal_kinds == ("failure", "repair")
    assert pattern.task_ids == ("task-1", "task-2")
    assert pattern.example_detail.endswith("deadbeefcafebabe")


def test_analyzer_is_bounded_and_deterministic():
    signals = tuple(
        ImprovementSignal("failure", str(i), f"failure-{chr(97 + i)}")
        for i in range(10)
    )

    analysis = analyze_signals(signals, min_occurrences=1, max_patterns=3)

    assert len(analysis.recurring_patterns) == 3
    assert [pattern.key for pattern in analysis.recurring_patterns] == [
        "failure-a",
        "failure-b",
        "failure-c",
    ]


def test_analyzer_ignores_success_signals():
    analysis = analyze_signals(
        (
            ImprovementSignal("success", None, "integration ready"),
            ImprovementSignal("repair", "task-1", "one-off repair"),
        )
    )

    assert analysis.failure_count == 0
    assert analysis.repair_count == 1
    assert analysis.recurring_patterns == ()


def test_analyzer_rejects_invalid_bounds():
    signals = (ImprovementSignal("failure", "task-1", "x"),)

    try:
        analyze_signals(signals, min_occurrences=0)
    except ValueError as exc:
        assert str(exc) == "min_occurrences must be >= 1"
    else:
        raise AssertionError("expected ValueError")

    try:
        analyze_signals(signals, max_patterns=0)
    except ValueError as exc:
        assert str(exc) == "max_patterns must be >= 1"
    else:
        raise AssertionError("expected ValueError")
