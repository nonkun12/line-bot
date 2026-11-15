import pytest

from core.revision_workflow import RevisionDraft, prepare_revision_draft, review_revision_draft


def _draft(**overrides):
    values = dict(
        request_id="req-1",
        task_id="task-1",
        revision_agent_id="revision-agent",
        target_agent_id="target-agent",
        original_reviewer_id="first-reviewer",
        content="Corrected evidence summary.",
        addressed_findings=("Add independent evidence.",),
    )
    values.update(overrides)
    return RevisionDraft(**values)


def test_revision_draft_is_inert_and_identity_bound():
    draft = _draft()
    assert draft.execution_authorized is False
    assert draft.target_agent_id == "target-agent"


def test_revision_draft_rejects_identity_collision_and_execution_authority():
    with pytest.raises(ValueError, match="must be distinct"):
        _draft(revision_agent_id="target-agent")
    with pytest.raises(ValueError, match="cannot authorize"):
        _draft(execution_authorized=True)


def test_revision_agent_prepares_bounded_draft_from_findings():
    seen = []

    def model(prompt):
        seen.append(prompt)
        return '{"content":"Added source citations.","addressed_findings":["Add independent evidence."]}'

    draft = prepare_revision_draft(
        request_id="req-1",
        task_id="task-1",
        revision_agent_id="revision-agent",
        target_agent_id="target-agent",
        original_reviewer_id="first-reviewer",
        original_result="Original summary.",
        findings=("Add independent evidence.",),
        model_call=model,
    )
    assert draft.content == "Added source citations."
    assert draft.execution_authorized is False
    assert "inert text only" in seen[0]


def test_revision_agent_cannot_claim_unprovided_finding():
    with pytest.raises(ValueError, match="only claim supplied findings"):
        prepare_revision_draft(
            request_id="req-1",
            task_id="task-1",
            revision_agent_id="revision-agent",
            target_agent_id="target-agent",
            original_reviewer_id="first-reviewer",
            original_result="Original summary.",
            findings=("Add independent evidence.",),
            model_call=lambda prompt: '{"content":"Updated.","addressed_findings":["Invented finding."]}',
        )


def test_independent_reviewer_must_be_fourth_identity():
    draft = _draft()
    with pytest.raises(ValueError, match="not independent"):
        review_revision_draft(
            draft,
            independent_reviewer_id="first-reviewer",
            model_call=lambda prompt: '{"verdict":"PASS","findings":[]}',
        )


def test_independent_review_is_separate_and_never_authorizes_execution():
    draft = _draft()
    review = review_revision_draft(
        draft,
        independent_reviewer_id="second-reviewer",
        model_call=lambda prompt: '{"verdict":"PASS","findings":[]}',
    )
    assert review.verdict == "PASS"
    assert review.independent_reviewer_id == "second-reviewer"
    assert review.execution_authorized is False


@pytest.mark.parametrize("payload", [
    "not json",
    '{"verdict":"APPROVED","findings":[]}',
])
def test_independent_review_rejects_malformed_or_unrecognized_output(payload):
    draft = _draft()
    with pytest.raises(ValueError):
        review_revision_draft(
            draft,
            independent_reviewer_id="second-reviewer",
            model_call=lambda prompt: payload,
        )


def test_revision_snapshot_reports_not_started_without_inventing_activity():
    from core.revision_workflow import revision_workflow_snapshot

    snapshot = revision_workflow_snapshot()
    assert snapshot["draft_status"] == "NOT_STARTED"
    assert snapshot["review_status"] == "NOT_STARTED"
    assert snapshot["execution_authorized"] is False


def test_revision_snapshot_requires_matching_review_chain():
    from core.revision_workflow import revision_workflow_snapshot, RevisionReview

    draft = _draft()
    review = RevisionReview(
        request_id="req-1",
        task_id="task-1",
        revision_agent_id="revision-agent",
        target_agent_id="target-agent",
        original_reviewer_id="first-reviewer",
        independent_reviewer_id="second-reviewer",
        verdict="PASS",
        findings=(),
    )
    snapshot = revision_workflow_snapshot(draft, review)
    assert snapshot["draft_status"] == "PREPARED"
    assert snapshot["review_status"] == "PASS"
    assert snapshot["execution_authorized"] is False

    mismatched = RevisionReview(
        request_id="req-2",
        task_id="task-1",
        revision_agent_id="revision-agent",
        target_agent_id="target-agent",
        original_reviewer_id="first-reviewer",
        independent_reviewer_id="second-reviewer",
        verdict="PASS",
        findings=(),
    )
    with pytest.raises(ValueError, match="does not match"):
        revision_workflow_snapshot(draft, mismatched)



def test_revision_coordinator_skips_all_model_calls_without_revision_request():
    from core.revision_workflow import run_revision_workflow_if_needed

    def forbidden(_prompt):
        raise AssertionError("model must not be called")

    snapshot = run_revision_workflow_if_needed(
        original_verdict="PASS",
        request_id="req-1",
        task_id="task-1",
        revision_agent_id="revision-agent",
        target_agent_id="target-agent",
        original_reviewer_id="first-reviewer",
        independent_reviewer_id="second-reviewer",
        original_result="Original result.",
        findings=("Finding.",),
        draft_model_call=forbidden,
        review_model_call=forbidden,
    )
    assert snapshot["draft_status"] == "NOT_STARTED"
    assert snapshot["execution_authorized"] is False


def test_revision_coordinator_requires_four_distinct_identities():
    from core.revision_workflow import run_revision_workflow_if_needed

    with pytest.raises(ValueError, match="four distinct"):
        run_revision_workflow_if_needed(
            original_verdict="NEEDS_REVISION",
            request_id="req-1",
            task_id="task-1",
            revision_agent_id="revision-agent",
            target_agent_id="target-agent",
            original_reviewer_id="first-reviewer",
            independent_reviewer_id="first-reviewer",
            original_result="Original result.",
            findings=("Finding.",),
            draft_model_call=lambda _prompt: "{}",
            review_model_call=lambda _prompt: "{}",
        )


def test_revision_coordinator_runs_draft_then_independent_review_and_persists_evidence():
    from core.revision_workflow import run_revision_workflow_if_needed

    calls = []
    persisted = []

    def draft_model(prompt):
        calls.append(("draft", prompt))
        return '{"content":"Revised text.","addressed_findings":["Finding."]}'

    def review_model(prompt):
        calls.append(("review", prompt))
        return '{"verdict":"PASS","findings":[]}'

    snapshot = run_revision_workflow_if_needed(
        original_verdict="NEEDS_REVISION",
        request_id="req-1",
        task_id="task-1",
        revision_agent_id="revision-agent",
        target_agent_id="target-agent",
        original_reviewer_id="first-reviewer",
        independent_reviewer_id="second-reviewer",
        original_result="Original result.",
        findings=("Finding.",),
        draft_model_call=draft_model,
        review_model_call=review_model,
        persist_snapshot=persisted.append,
    )
    assert [kind for kind, _ in calls] == ["draft", "review"]
    assert snapshot["review_status"] == "PASS"
    assert snapshot["execution_authorized"] is False
    assert persisted == [snapshot]


def test_revision_coordinator_propagates_persistence_failure_without_execution():
    from core.revision_workflow import run_revision_workflow_if_needed

    with pytest.raises(RuntimeError, match="audit unavailable"):
        run_revision_workflow_if_needed(
            original_verdict="NEEDS_REVISION",
            request_id="req-1",
            task_id="task-1",
            revision_agent_id="revision-agent",
            target_agent_id="target-agent",
            original_reviewer_id="first-reviewer",
            independent_reviewer_id="second-reviewer",
            original_result="Original result.",
            findings=("Finding.",),
            draft_model_call=lambda _prompt: '{"content":"Revised.","addressed_findings":["Finding."]}',
            review_model_call=lambda _prompt: '{"verdict":"PASS","findings":[]}',
            persist_snapshot=lambda _snapshot: (_ for _ in ()).throw(RuntimeError("audit unavailable")),
        )
