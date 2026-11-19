from core.self_improvement import ImprovementSignal
from core.self_improvement_analyzer import ImprovementAnalysis, ImprovementPattern
from core.self_improvement_proposals import generate_improvement_proposals


def _analysis(count=2):
    return ImprovementAnalysis(
        total_signals=count,
        failure_count=count,
        repair_count=0,
        recurring_patterns=(
            ImprovementPattern(
                key="timeout while running tests",
                count=count,
                signal_kinds=("failure",),
                task_ids=("task-1",),
                example_detail="timeout while running tests",
            ),
        ),
    )


def test_generates_bounded_deterministic_proposal_for_recurring_pattern():
    signals = (
        ImprovementSignal("failure", "task-1", "timeout while running tests"),
        ImprovementSignal("failure", "task-1", "timeout while running tests"),
    )
    proposals = generate_improvement_proposals(
        _analysis(),
        signals,
        target_paths=("tests/test_runtime.py", "core/runtime_helper.py"),
        max_proposals=1,
    )

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.title.startswith("Investigate recurring failure:")
    assert proposal.task is not None
    assert proposal.task.role.value == "debugger"
    assert proposal.task.resources == frozenset({"task-1"})
    assert len(proposal.signals) == 2


def test_non_recurring_analysis_produces_no_proposal():
    analysis = ImprovementAnalysis(
        total_signals=1,
        failure_count=1,
        repair_count=0,
        recurring_patterns=(),
    )
    assert generate_improvement_proposals(
        analysis,
        target_paths=("core/runtime_helper.py",),
    ) == ()


def test_protected_paths_fail_closed():
    proposals = generate_improvement_proposals(
        _analysis(),
        target_paths=("core/self_improvement_policy.py",),
    )
    assert proposals == ()


def test_empty_target_paths_fail_closed():
    assert generate_improvement_proposals(_analysis()) == ()


def test_max_proposals_is_bounded_and_validated():
    analysis = ImprovementAnalysis(
        total_signals=4,
        failure_count=4,
        repair_count=0,
        recurring_patterns=tuple(
            ImprovementPattern(
                key=f"failure-{i}",
                count=2,
                signal_kinds=("failure",),
                task_ids=(f"task-{i}",),
                example_detail=f"failure-{i}",
            )
            for i in range(4)
        ),
    )
    proposals = generate_improvement_proposals(
        analysis,
        target_paths=("core/runtime_helper.py",),
        max_proposals=2,
    )
    assert len(proposals) == 2

    try:
        generate_improvement_proposals(
            analysis,
            target_paths=("core/runtime_helper.py",),
            max_proposals=0,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("max_proposals=0 must fail")
