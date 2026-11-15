from __future__ import annotations

import pytest

from core.multi_agent import AgentRole, AgentTask
from core.request_scoped_agents import (
    PeerReview,
    PeerReviewCoordinator,
    RequestScopedAgentFactory,
    ReviewVerdict,
)


def task(task_id: str, role: AgentRole, resources: frozenset[str] = frozenset()) -> AgentTask:
    return AgentTask(task_id=task_id, role=role, instruction=f"Do {task_id}", resources=resources)


def test_factory_creates_request_scoped_identities_and_parallel_batches() -> None:
    team = RequestScopedAgentFactory().create(
        "req-1",
        [
            task("research", AgentRole.GENERAL, frozenset({"docs"})),
            task("test", AgentRole.TESTER, frozenset({"tests"})),
        ],
    )
    assert len(team.agents) == 2
    assert team.agents[0].request_id == "req-1"
    assert team.agents[0].agent_id != team.agents[1].agent_id
    assert len(team.batches) == 1
    assert {agent.role for agent in team.agents} == {AgentRole.GENERAL, AgentRole.TESTER}


def test_factory_creates_distinct_clones_for_tasks_with_same_role() -> None:
    team = RequestScopedAgentFactory().create(
        "req-same-role",
        [
            task("part-a", AgentRole.GENERAL),
            task("part-b", AgentRole.GENERAL),
        ],
    )
    assert len(team.agents) == 2
    assert team.agents[0].role is team.agents[1].role is AgentRole.GENERAL
    assert team.agents[0].agent_id != team.agents[1].agent_id
    assert team.agents[0].task_ids != team.agents[1].task_ids


def test_factory_rejects_more_than_six_tasks() -> None:
    tasks = [task(str(i), AgentRole.GENERAL) for i in range(7)]
    with pytest.raises(ValueError, match="task count exceeds"):
        RequestScopedAgentFactory().create("req-1", tasks)


def test_factory_rejects_invalid_dependency_graph() -> None:
    invalid = AgentTask(
        task_id="child",
        role=AgentRole.TESTER,
        instruction="test",
        depends_on=("missing",),
    )
    with pytest.raises(ValueError, match="missing dependency"):
        RequestScopedAgentFactory().create("req-1", [invalid])


def test_peer_review_pass_requires_every_agent_to_be_reviewed() -> None:
    team = RequestScopedAgentFactory().create(
        "req-2",
        [task("a", AgentRole.GENERAL), task("b", AgentRole.TESTER)],
    )
    a, b = team.agents
    decision = PeerReviewCoordinator().decide(
        team,
        [
            PeerReview(a.agent_id, b.agent_id, ReviewVerdict.PASS),
            PeerReview(b.agent_id, a.agent_id, ReviewVerdict.PASS),
        ],
    )
    assert decision.status == "PASS"
    assert not decision.blocked_agent_ids
    assert len(decision.accepted_agent_ids) == 2


def test_peer_review_blocks_on_adverse_verdict_or_missing_review() -> None:
    team = RequestScopedAgentFactory().create(
        "req-3",
        [task("a", AgentRole.GENERAL), task("b", AgentRole.TESTER)],
    )
    a, b = team.agents
    decision = PeerReviewCoordinator().decide(
        team,
        [PeerReview(a.agent_id, b.agent_id, ReviewVerdict.NEEDS_REVISION)],
    )
    assert decision.status == "BLOCKED"
    assert len(decision.blocked_agent_ids) == 2


def test_peer_review_rejects_cross_request_agent_identity() -> None:
    team = RequestScopedAgentFactory().create(
        "req-4",
        [task("a", AgentRole.GENERAL), task("b", AgentRole.TESTER)],
    )
    a, b = team.agents
    with pytest.raises(ValueError, match="outside this request"):
        PeerReviewCoordinator().decide(
            team,
            [PeerReview("foreign-agent", b.agent_id, ReviewVerdict.PASS)],
        )
