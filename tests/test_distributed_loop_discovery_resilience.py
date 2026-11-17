from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "distributed-autonomous-loop.yml"


def _step_block(workflow: str, name: str) -> str:
    marker = f"      - name: {name}\n"
    start = workflow.index(marker)
    end = workflow.find("\n      - name:", start + len(marker))
    return workflow[start:] if end < 0 else workflow[start:end]


def test_issue_inventory_failure_does_not_skip_bounded_runtime_task():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    inventory = _step_block(workflow, "Load all existing issues for candidate deduplication")
    runner = _step_block(workflow, "Run one bounded autonomous task")

    assert "id: load_issues" in inventory
    assert "continue-on-error: true" in inventory
    assert "for attempt in 1 2 3" in inventory
    assert "steps.load_issues" not in runner


def test_issue_dependent_discovery_steps_require_successful_inventory():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    dependent_steps = (
        "Publish read-only task review backlog digest",
        "Generate review-only task proposals when catalog is exhausted",
        "Analyze catalog exhaustion without changing execution state (Work Finder AI)",
        "Create bounded review-only task issues from analyzer findings",
    )
    for name in dependent_steps:
        block = _step_block(workflow, name)
        assert "steps.load_issues.outcome == 'success'" in block


def test_review_only_candidate_failure_does_not_fail_task_execution_job():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    candidates = _step_block(workflow, "Build review-only self-improvement candidate pool")
    assert "if: always()" in candidates
    assert "continue-on-error: true" in candidates
