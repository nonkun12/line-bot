import pytest

from agents.media.human_creative_decision import record_human_creative_decision


def _comparison(complete=True):
    return {
        "schema_version": "audiovisual-creator-candidate-comparison.v1",
        "comparisons": [
            {"candidate_id": "candidate-a", "structural_review_complete": complete}
        ],
    }


def _decision(action="select_candidate", candidate_id="candidate-a"):
    return {
        "action": action,
        "candidate_id": candidate_id,
        "rationale": "The musical phrasing and visual pacing support the scene.",
        "human_confirmed_listening": True,
        "human_confirmed_viewing": True,
    }


def test_select_requires_explicit_human_listening_and_viewing():
    result = record_human_creative_decision(_comparison(), _decision())
    assert result["decision_recorded"] is True
    assert result["action"] == "select_candidate"
    assert result["execution_policy"]["publication_authorized"] is False


def test_select_rejects_candidate_with_structural_findings():
    with pytest.raises(ValueError, match="structural completeness"):
        record_human_creative_decision(_comparison(False), _decision())


def test_missing_listening_or_viewing_confirmation_fails_closed():
    decision = _decision()
    decision["human_confirmed_viewing"] = False
    with pytest.raises(ValueError, match="viewing confirmation"):
        record_human_creative_decision(_comparison(), decision)


def test_revision_request_must_target_known_candidate():
    decision = _decision("request_revision", "unknown")
    with pytest.raises(ValueError, match="must exist"):
        record_human_creative_decision(_comparison(), decision)


def test_reject_all_does_not_accept_candidate_id():
    decision = _decision("reject_all", "candidate-a")
    with pytest.raises(ValueError, match="must not specify"):
        record_human_creative_decision(_comparison(), decision)


def test_reject_all_records_reason_without_authorizing_publication():
    decision = _decision("reject_all", None)
    result = record_human_creative_decision(_comparison(), decision)
    assert result["action"] == "reject_all"
    assert result["candidate_id"] is None
