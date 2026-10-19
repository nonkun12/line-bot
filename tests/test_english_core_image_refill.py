from __future__ import annotations

import pytest

from scripts.english_core_image_refill import build_refill_plan


def candidate(word):
    return {
        "word": word,
        "pronunciation": "test",
        "core_image": "review this meaning",
        "parts": "source needed",
        "related": [],
        "example": "A source-backed example.",
    }


def test_refill_plan_is_bounded_and_never_authorizes_runtime_mutation():
    candidates = [candidate(f"word{i}") for i in range(6)]
    plan = build_refill_plan(candidates, set(), limit=4, target=1000)
    assert len(plan["tasks"]) == 4
    assert plan["truncated"] is True
    assert plan["auto_approval"] is False
    assert plan["runtime_lexicon_mutation_authorized"] is False
    assert all(task["status"] == "PENDING_REVIEW" for task in plan["tasks"])
    assert all(task["requires_dictionary_source"] for task in plan["tasks"])


def test_reviewed_words_are_not_refilled_and_candidates_are_deterministic():
    candidates = [candidate("zebra"), candidate("apple"), candidate("mango")]
    a = build_refill_plan(candidates, {"mango"}, limit=4)
    b = build_refill_plan(list(reversed(candidates)), {"mango"}, limit=4)
    assert [x["word"] for x in a["tasks"]] == ["apple", "zebra"]
    assert a["tasks"] == b["tasks"]


def test_duplicate_or_invalid_candidates_are_reported():
    plan = build_refill_plan([candidate("apple"), candidate("apple"), {"word": "../bad"}], set())
    assert plan["duplicate_candidates"] == 1
    assert plan["invalid_candidates"] == 1


@pytest.mark.parametrize("limit", [0, 5, True, 1.5])
def test_refill_plan_rejects_unbounded_or_invalid_limits(limit):
    with pytest.raises(ValueError):
        build_refill_plan([], set(), limit=limit)


def test_refill_plan_reports_gap_without_fabricating_missing_entries():
    plan = build_refill_plan([candidate("apple")], set(), target=1000)
    assert plan["candidate_pool_gap"] == 999
    assert plan["reviewed_gap"] == 1000
    assert len(plan["tasks"]) == 1
    assert plan["tasks"][0]["runtime_lexicon_mutation_authorized"] is False
