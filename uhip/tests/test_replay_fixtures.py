import json
from pathlib import Path


FIXTURES = Path(__file__).parent / "fixtures" / "replay-events.json"


def _recognition_accepts(event: dict) -> bool:
    confidence = event.get("confidence", {}).get("calibrated", 1.0)
    return (
        confidence >= 0.80
        and event.get("hand_count", 1) == 1
        and event.get("person_count", 1) == 1
        and not event.get("out_of_frame", False)
        and event.get("ttl_ms", 500) > 0
    )


def test_phase0_replay_fixture_expectations_are_deterministic():
    cases = json.loads(FIXTURES.read_text(encoding="utf-8"))
    assert cases

    for case in cases:
        accepted = _recognition_accepts(case["event"])
        assert accepted is (case["expected"] == "accept"), case["case"]


def test_phase0_fixture_corpus_has_positive_and_negative_cases():
    cases = json.loads(FIXTURES.read_text(encoding="utf-8"))
    outcomes = {case["expected"] for case in cases}
    assert outcomes == {"accept", "reject"}
