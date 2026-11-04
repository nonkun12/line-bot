import pytest

from agents.media.candidate_comparison import compare_creator_revision_candidates


def _briefs():
    return {
        "schema_version": "audiovisual-creator-revision-briefs.v1",
        "briefs": [
            {
                "brief_id": "P1-CONSERVATIVE",
                "variant": "conservative",
                "domain": "music",
                "scene_id": "SC01",
                "preserve": ["story", "sync"],
                "deliverables": ["change_summary", "alternatives"],
            },
            {
                "brief_id": "P1-EXPLORATORY",
                "variant": "exploratory",
                "domain": "music",
                "scene_id": "SC01",
                "preserve": ["story", "sync"],
                "deliverables": ["change_summary", "alternatives"],
            },
        ],
    }


def _candidate(candidate_id, brief_id, **extra):
    return {
        "candidate_id": candidate_id,
        "brief_id": brief_id,
        "preserved_elements": ["story", "sync"],
        "deliverables": ["change_summary", "alternatives"],
        **extra,
    }


def _critic(findings=None):
    return {
        "schema_version": "audiovisual-revision-candidate-critic.v1",
        "status": "REVIEW_REQUIRED" if findings else "STRUCTURAL_CHECKS_PASS",
        "findings": findings or [],
    }


def test_comparison_orders_structural_findings_without_selecting_winner():
    candidates = [
        _candidate("alt-b", "P1-EXPLORATORY"),
        _candidate("alt-a", "P1-CONSERVATIVE"),
    ]
    report = _critic([
        {"severity": "warning", "code": "candidate_incomplete", "candidate_id": "alt-b"},
    ])

    result = compare_creator_revision_candidates(_briefs(), candidates, report)

    assert [row["candidate_id"] for row in result["comparisons"]] == ["alt-a", "alt-b"]
    assert result["comparisons"][0]["structural_review_complete"] is True
    assert result["comparisons"][1]["critic_findings"]["warning"] == 1
    assert result["selection"]["creative_winner_selected"] is False
    assert result["execution_policy"]["publication_authorized"] is False


def test_missing_preservation_and_deliverables_are_visible():
    candidate = _candidate("alt-a", "P1-CONSERVATIVE", preserved_elements=["story"], deliverables=[])

    result = compare_creator_revision_candidates(_briefs(), [candidate], _critic())

    row = result["comparisons"][0]
    assert row["missing_preservation_declarations"] == ["sync"]
    assert row["missing_required_deliverables"] == ["change_summary", "alternatives"]
    assert row["structural_review_complete"] is False


def test_global_findings_are_not_silently_assigned_to_a_candidate():
    result = compare_creator_revision_candidates(
        _briefs(),
        [_candidate("alt-a", "P1-CONSERVATIVE")],
        _critic([{"severity": "warning", "code": "global_coverage_gap", "candidate_id": None}]),
    )

    assert result["global_critic_findings"] == [
        {"severity": "warning", "code": "global_coverage_gap"}
    ]
    assert result["comparisons"][0]["critic_findings"]["warning"] == 0


def test_unknown_candidate_reference_fails_closed():
    with pytest.raises(ValueError, match="unknown candidate"):
        compare_creator_revision_candidates(
            _briefs(),
            [_candidate("alt-a", "P1-CONSERVATIVE")],
            _critic([{"severity": "blocker", "code": "unsafe", "candidate_id": "missing"}]),
        )


def test_duplicate_candidate_ids_fail_closed():
    with pytest.raises(ValueError, match="unique"):
        compare_creator_revision_candidates(
            _briefs(),
            [
                _candidate("same", "P1-CONSERVATIVE"),
                _candidate("same", "P1-EXPLORATORY"),
            ],
            _critic(),
        )


def test_unsafe_execution_candidate_is_rejected():
    with pytest.raises(ValueError, match="unsafe"):
        compare_creator_revision_candidates(
            _briefs(),
            [_candidate("alt-a", "P1-CONSERVATIVE", publication_requested=True)],
            _critic(),
        )
