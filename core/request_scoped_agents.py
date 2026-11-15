"""Request-scoped logical agent instances and bounded peer-review coordination.

This layer creates isolated agent identities and work assignments. It does not
start model providers, grant tools, mutate repositories, or authorize execution.
Provider adapters must be injected by a separately approved runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Iterable

from .multi_agent import AgentRole, AgentTask, plan_batches

_MAX_REQUEST_ID = 128
_MAX_AGENTS = 6
_MAX_REVIEWS = 6


class ReviewVerdict(str, Enum):
    PASS = "PASS"
    NEEDS_REVISION = "NEEDS_REVISION"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class AgentInstance:
    """A request-local identity; it carries no credentials or tool permissions."""

    agent_id: str
    request_id: str
    role: AgentRole
    task_ids: tuple[str, ...]
    context_key: str


@dataclass(frozen=True)
class PeerReview:
    reviewer_id: str
    target_agent_id: str
    verdict: ReviewVerdict
    findings: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentTeam:
    request_id: str
    agents: tuple[AgentInstance, ...]
    batches: tuple[object, ...]
    reviewer_agents: tuple[AgentInstance, ...] = ()


@dataclass(frozen=True)
class RevisionRequest:
    reviewer_id: str
    target_agent_id: str
    findings: tuple[str, ...]


@dataclass(frozen=True)
class ReviewDecision:
    status: str
    accepted_agent_ids: tuple[str, ...]
    blocked_agent_ids: tuple[str, ...]
    findings: tuple[str, ...]
    revision_requests: tuple[RevisionRequest, ...] = ()


class RequestScopedAgentFactory:
    """Create at most six isolated logical agents for one request."""

    def __init__(self, *, max_agents: int = _MAX_AGENTS) -> None:
        if not isinstance(max_agents, int) or isinstance(max_agents, bool):
            raise ValueError("max_agents must be an integer")
        if not 1 <= max_agents <= _MAX_AGENTS:
            raise ValueError(f"max_agents must be between 1 and {_MAX_AGENTS}")
        self.max_agents = max_agents

    @staticmethod
    def _validate_request_id(request_id: str) -> None:
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_id is required")
        if len(request_id) > _MAX_REQUEST_ID:
            raise ValueError("request_id exceeds 128 characters")

    def create(self, request_id: str, tasks: Iterable[AgentTask]) -> AgentTeam:
        self._validate_request_id(request_id)
        task_list = tuple(tasks)
        if not task_list:
            raise ValueError("at least one task is required")
        if len(task_list) > self.max_agents:
            raise ValueError("task count exceeds configured agent limit")

        # plan_batches validates duplicate IDs, missing dependencies and cycles.
        batches = plan_batches(task_list)
        agents: list[AgentInstance] = []
        for task in task_list:
            digest = sha256(
                (request_id + "|" + task.role.value + "|" + task.task_id).encode()
            ).hexdigest()[:16]
            agents.append(
                AgentInstance(
                    agent_id=f"{request_id}:{task.role.value}:{digest}",
                    request_id=request_id,
                    role=task.role,
                    task_ids=(task.task_id,),
                    context_key=digest,
                )
            )
        reviewer_agents: tuple[AgentInstance, ...] = ()
        # A one-task request still needs an independent reviewer. This bounded,
        # review-only identity has no task assignment and is never an executor.
        if len(agents) == 1:
            target = agents[0]
            digest = sha256(
                (request_id + "|reviewer|" + target.agent_id).encode()
            ).hexdigest()[:16]
            reviewer_agents = (
                AgentInstance(
                    agent_id=f"{request_id}:reviewer:{digest}",
                    request_id=request_id,
                    role=target.role,
                    task_ids=(),
                    context_key=digest,
                ),
            )
        return AgentTeam(request_id, tuple(agents), batches, reviewer_agents)


class PeerReviewCoordinator:
    """Accept only bounded, identity-bound reviews; fail closed on disagreement."""

    def __init__(self, *, max_reviews: int = _MAX_REVIEWS) -> None:
        if not isinstance(max_reviews, int) or isinstance(max_reviews, bool):
            raise ValueError("max_reviews must be an integer")
        if not 1 <= max_reviews <= _MAX_REVIEWS:
            raise ValueError(f"max_reviews must be between 1 and {_MAX_REVIEWS}")
        self.max_reviews = max_reviews

    def decide(
        self,
        team: AgentTeam,
        reviews: Iterable[PeerReview],
    ) -> ReviewDecision:
        review_list = tuple(reviews)
        if len(review_list) > self.max_reviews:
            raise ValueError("review count exceeds configured limit")

        targets = {agent.agent_id for agent in team.agents}
        known_reviewers = targets | {agent.agent_id for agent in team.reviewer_agents}
        seen: set[tuple[str, str]] = set()
        by_target: dict[str, list[PeerReview]] = {agent_id: [] for agent_id in targets}
        findings: list[str] = []
        revision_requests: list[RevisionRequest] = []

        for review in review_list:
            if review.reviewer_id not in known_reviewers or review.target_agent_id not in targets:
                raise ValueError("review references an agent outside this request")
            if review.reviewer_id == review.target_agent_id:
                raise ValueError("self-review is not allowed")
            pair = (review.reviewer_id, review.target_agent_id)
            if pair in seen:
                raise ValueError("duplicate peer review")
            seen.add(pair)
            if not isinstance(review.verdict, ReviewVerdict):
                raise ValueError("invalid review verdict")
            if len(review.findings) > 8 or any(
                not isinstance(item, str) or not item.strip() or len(item) > 500
                for item in review.findings
            ):
                raise ValueError("review findings exceed bounds")
            if review.verdict is ReviewVerdict.NEEDS_REVISION and not review.findings:
                raise ValueError("revision request requires actionable findings")
            by_target[review.target_agent_id].append(review)
            findings.extend(review.findings)
            if review.verdict is ReviewVerdict.NEEDS_REVISION:
                revision_requests.append(
                    RevisionRequest(
                        reviewer_id=review.reviewer_id,
                        target_agent_id=review.target_agent_id,
                        findings=review.findings,
                    )
                )

        accepted: list[str] = []
        blocked: list[str] = []
        for agent_id, target_reviews in by_target.items():
            # Every agent needs at least one independent PASS and no adverse verdict.
            if target_reviews and all(
                item.verdict is ReviewVerdict.PASS for item in target_reviews
            ):
                accepted.append(agent_id)
            else:
                blocked.append(agent_id)

        has_hard_block = any(
            item.verdict is ReviewVerdict.BLOCKED
            for target_reviews in by_target.values()
            for item in target_reviews
        )
        status = (
            "PASS" if not blocked
            else "BLOCKED" if has_hard_block or not revision_requests
            else "NEEDS_REVISION"
        )
        return ReviewDecision(
            status=status,
            accepted_agent_ids=tuple(sorted(accepted)),
            blocked_agent_ids=tuple(sorted(blocked)),
            findings=tuple(findings),
            revision_requests=tuple(revision_requests),
        )


__all__ = [
    "AgentInstance",
    "AgentTeam",
    "PeerReview",
    "PeerReviewCoordinator",
    "RequestScopedAgentFactory",
    "ReviewDecision",
    "RevisionRequest",
    "ReviewVerdict",
]
