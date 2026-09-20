from core.agent_runtime import RuntimeReport
from core.self_improvement_cycle import run_self_improvement_cycle


def test_cycle_persists_signals_and_generates_recurring_proposals(tmp_path):
    path = tmp_path / "self-improvement.jsonl"
    first = RuntimeReport(
        (),
        failed_task_id="tests",
        error="pytest timeout",
        rounds=1,
        repair_attempts=1,
        integration_ready=False,
    )
    second = RuntimeReport(
        (),
        failed_task_id="tests",
        error="pytest timeout",
        rounds=1,
        repair_attempts=1,
        integration_ready=False,
    )

    one = run_self_improvement_cycle(
        first,
        path,
        target_paths=("tests/test_runtime.py",),
    )
    assert one.new_signals
    assert one.proposals == ()

    two = run_self_improvement_cycle(
        second,
        path,
        target_paths=("tests/test_runtime.py",),
    )
    assert len(two.all_signals) == 4
    assert two.analysis.failure_count == 2
    assert two.analysis.repair_count == 2
    assert two.analysis.has_recurring_pattern
    assert len(two.proposals) == 2
    assert {proposal.title for proposal in two.proposals} == {
        "Investigate recurring failure: development required <n> repair attempt(s)",
        "Investigate recurring failure: pytest timeout",
    }
    assert all(proposal.task is not None for proposal in two.proposals)


def test_cycle_protected_targets_fail_closed(tmp_path):
    report = RuntimeReport(
        (),
        failed_task_id="tests",
        error="pytest timeout",
        rounds=1,
        repair_attempts=1,
        integration_ready=False,
    )
    result = run_self_improvement_cycle(
        report,
        tmp_path / "self-improvement.jsonl",
        target_paths=("core/self_improvement_policy.py",),
    )

    assert result.analysis.total_signals == 2
    assert result.proposals == ()


def test_cycle_rejects_non_runtime_report(tmp_path):
    try:
        run_self_improvement_cycle(
            object(),  # type: ignore[arg-type]
            tmp_path / "self-improvement.jsonl",
            target_paths=("tests/test_runtime.py",),
        )
    except TypeError as exc:
        assert str(exc) == "report must be a RuntimeReport"
    else:
        raise AssertionError("expected TypeError")
