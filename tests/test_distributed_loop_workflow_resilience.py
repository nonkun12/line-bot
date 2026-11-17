"""Contract tests for Distributed Loop preflight resilience."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "distributed-autonomous-loop.yml"


def test_issue_discovery_retries_and_validates_paginated_api_responses():
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("- name: Load all existing issues for candidate deduplication")
    end = text.index("- name: Publish read-only task review backlog digest", start)
    step = text[start:end]
    assert 'while [ "$attempt" -le 3 ]' in step
    assert 'gh api --paginate "$endpoint"' in step
    assert "jq -es" in step
    assert 'sleep "$((attempt * 2))"' in step
    assert "task discovery is blocked" in step
    assert r"\${" not in step


def test_candidate_pool_distinguishes_skipped_task_from_missing_task_evidence():
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("- name: Build review-only self-improvement candidate pool")
    end = text.index("- name: Upload review-only self-improvement candidates", start)
    step = text[start:end]
    assert "RUN_TASK_CONCLUSION" in step
    assert '!= "skipped"' in step
    assert "missing after an attempted task" in step
    assert "loading the existing durable state branch read-only" in step
