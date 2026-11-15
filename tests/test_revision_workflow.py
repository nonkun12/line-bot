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
