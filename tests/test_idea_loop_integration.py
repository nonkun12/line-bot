import os

from core.line_development_runtime import _prepare_idea_stage


def test_idea_stage_is_opt_in(monkeypatch):
    monkeypatch.delenv("IDEA_MODE", raising=False)
    instruction, task_id, blocked = _prepare_idea_stage("hand-sign")
    assert instruction == "hand-sign"
    assert task_id is None
    assert blocked is None


def test_idea_stage_blocks_without_explicit_acceptance(monkeypatch):
    monkeypatch.setenv("IDEA_MODE", "1")
    monkeypatch.delenv("IDEA_ACCEPTED_ID", raising=False)
    instruction, task_id, blocked = _prepare_idea_stage("hand-sign")
    assert instruction == "hand-sign"
    assert task_id is None
    assert blocked == "IDEA acceptance required"


def test_idea_stage_handoffs_only_explicitly_accepted_proposal(monkeypatch):
    monkeypatch.setenv("IDEA_MODE", "1")
    monkeypatch.setenv("IDEA_ACCEPTED_ID", "specialize-3")
    monkeypatch.setenv("IDEA_ACCEPTANCE_REASON", "human accepted this bounded proposal")
    instruction, task_id, blocked = _prepare_idea_stage("hand-sign")
    assert blocked is None
    assert task_id == "develop-from-specialize-3"
    assert "accepted IDEA proposal" in instruction
    assert "human accepted this bounded proposal" in instruction
