from core.creator_critic import CriticEvaluation, ImprovementCandidate
from core.rsi_executor import EvidenceLedger, canonical_digest
from core.rsi_orchestra import REAHandoff, REAReview, OrchestraRSIBatch
from core.rsi_supervisor import RSISupervisorBatch
from scripts.rsi_orchestra_control_tower_adapter import coordinate_rsi_orchestra_batch

REPO = "nonkun12/line-bot"
HEAD = "a" * 40


def make_batch(ledger, *, status="PASS", event_id="orchestra-rea:test-event"):
    candidate = ImprovementCandidate(
        candidate_id="creator-1",
        objective="objective",
        proposal="proposal",
    )
    candidate_digest = canonical_digest({
        "candidate_id": candidate.candidate_id,
        "objective": candidate.objective,
        "proposal": candidate.proposal,
        "constraints": list(candidate.constraints),
        "evidence": dict(candidate.evidence),
    })
    handoff = REAHandoff(
        task_id="rsi:experiment-1",
        repository=REPO,
        head_sha=HEAD,
        experiment_id="experiment-1",
        plan_digest="b" * 64,
        candidate_digest=candidate_digest,
        evidence_digest="d" * 64,
    )
    evaluation = CriticEvaluation(
        candidate_id="creator-1",
        passed=status == "PASS",
        score=0.95 if status == "PASS" else 0.4,
        accuracy=1.0,
        stability=1.0,
        efficiency=0.8,
        safety=1.0 if status == "PASS" else 0.2,
        feedback="reviewed",
    )
    payload = {
        "task_id": handoff.task_id,
        "repository": handoff.repository,
        "head_sha": handoff.head_sha,
        "experiment_id": handoff.experiment_id,
        "plan_digest": handoff.plan_digest,
        "candidate_digest": handoff.candidate_digest,
        "evidence_digest": handoff.evidence_digest,
        "status": status,
        "reason_code": None,
        "candidate_id": candidate.candidate_id,
        "critic_decision": evaluation.passed,
        "critic_score": evaluation.score,
        "critic_feedback_digest": canonical_digest(evaluation.feedback),
        "execution_authorized": False,
        "patch_authorized": False,
        "merge_deploy_authorized": False,
        "hold_clear_authorized": False,
    }
    ledger.append(event_id, "orchestra_rea_review", payload)
    review = REAReview(
        handoff, candidate, evaluation, status, evidence_event_id=event_id,
    )
    proposal_batch = RSISupervisorBatch((), 0, "MAX_CYCLES_REACHED")
    batch_status = (
        "REVIEW_PASS_PROPOSAL_ONLY" if status == "PASS"
        else "REVIEW_REQUIRED" if status == "FAIL" else "BLOCKED"
    )
    return OrchestraRSIBatch(proposal_batch, (review,), batch_status)


def test_control_tower_accepts_only_ledger_bound_proposal_review(tmp_path):
    ledger = EvidenceLedger(tmp_path / "tower.sqlite")
    batch = make_batch(ledger)
    result = coordinate_rsi_orchestra_batch(
        batch, ledger=ledger, expected_repository=REPO, expected_head_sha=HEAD,
    )
    assert result["status"] == "PASS"
    assert result["next_action"] == "REQUEST_HUMAN_REVIEW"
    assert result["allow_continue"] is False
    assert result["proposal_only"] is True
    assert result["execution_authorized"] is False
    assert result["merge_deploy_authorized"] is False
    assert result["review_evidence_event_ids"] == ["orchestra-rea:test-event"]


def test_control_tower_blocks_wrong_head_and_missing_review_evidence(tmp_path):
    ledger = EvidenceLedger(tmp_path / "tower.sqlite")
    batch = make_batch(ledger)
    wrong_head = coordinate_rsi_orchestra_batch(
        batch, ledger=ledger, expected_repository=REPO, expected_head_sha="f" * 40,
    )
    assert wrong_head["status"] == "BLOCKED"
    assert wrong_head["allow_continue"] is False

    missing = make_batch(ledger, event_id="orchestra-rea:missing")
    missing_review = missing.reviews[0]
    no_event = REAReview(
        missing_review.handoff, missing_review.candidate, missing_review.evaluation,
        "PASS", evidence_event_id="orchestra-rea:not-present",
    )
    missing_batch = OrchestraRSIBatch(
        missing.proposal_batch, (no_event,), "REVIEW_PASS_PROPOSAL_ONLY",
    )
    blocked = coordinate_rsi_orchestra_batch(
        missing_batch, ledger=ledger, expected_repository=REPO, expected_head_sha=HEAD,
    )
    assert blocked["status"] == "BLOCKED"
    assert blocked["reason_code"] == "review_evidence_missing_or_tampered"


def test_control_tower_maps_critic_failure_to_review_required(tmp_path):
    ledger = EvidenceLedger(tmp_path / "tower.sqlite")
    batch = make_batch(ledger, status="FAIL", event_id="orchestra-rea:failed")
    result = coordinate_rsi_orchestra_batch(
        batch, ledger=ledger, expected_repository=REPO, expected_head_sha=HEAD,
    )
    assert result["status"] == "FAIL"
    assert result["next_action"] == "REPORT_REVIEW_REQUIRED"
    assert result["execution_authorized"] is False
