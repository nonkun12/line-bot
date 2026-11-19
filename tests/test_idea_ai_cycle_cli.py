from __future__ import annotations

from core.idea_research_cycle import IdeaResearchCycle
from scripts.idea_ai_cycle import run_cycle


def test_run_cycle_creates_and_resumes_local_snapshot(tmp_path):
    database = tmp_path / "idea-ai.sqlite"

    first = run_cycle("Improve autonomous development", str(database))
    assert first.focus == "Improve autonomous development"
    assert len(first.ideas) > 0

    second = run_cycle("Improve autonomous development", str(database))
    assert isinstance(second, IdeaResearchCycle)
    assert second.focus == first.focus
    assert len(second.ideas) > 0


def test_run_cycle_rejects_different_focus_for_existing_namespace(tmp_path):
    database = tmp_path / "idea-ai.sqlite"
    run_cycle("Original focus", str(database))

    try:
        run_cycle("Different focus", str(database))
    except ValueError as exc:
        assert "new namespace" in str(exc)
    else:
        raise AssertionError("expected focus mismatch to be rejected")
