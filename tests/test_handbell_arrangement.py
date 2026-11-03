import pytest

from agents.music.handbell import validate_handbell_arrangement


def _arrangement():
    return {
        "tempo_bpm": 96,
        "beats_per_measure": 4,
        "performers": [{"id": "P1"}, {"id": "P2"}],
        "bells": [
            {"id": "C5", "pitch": "C5"},
            {"id": "E5", "pitch": "E5"},
            {"id": "G5", "pitch": "G5"},
        ],
        "events": [
            {"start_beat": 0, "duration_beats": 1, "pitch": "C5", "bell_id": "C5", "performer_id": "P1"},
            {"start_beat": 0, "duration_beats": 1, "pitch": "E5", "bell_id": "E5", "performer_id": "P1"},
            {"start_beat": 1, "duration_beats": 1, "pitch": "G5", "bell_id": "G5", "performer_id": "P2"},
        ],
    }


def test_valid_handbell_arrangement_respects_inventory_and_two_hands():
    result = validate_handbell_arrangement(_arrangement())
    assert result["valid"] is True
    assert result["event_count"] == 3


def test_rejects_event_using_unknown_bell_or_wrong_pitch():
    arrangement = _arrangement()
    arrangement["events"][0]["bell_id"] = "D5"
    assert "event_bell_unknown" in {e["code"] for e in validate_handbell_arrangement(arrangement)["errors"]}

    arrangement = _arrangement()
    arrangement["events"][0]["pitch"] = "D5"
    assert "event_pitch_does_not_match_bell" in {e["code"] for e in validate_handbell_arrangement(arrangement)["errors"]}


def test_rejects_same_physical_bell_with_overlapping_events():
    arrangement = _arrangement()
    arrangement["events"][1]["bell_id"] = "C5"
    arrangement["events"][1]["pitch"] = "C5"
    result = validate_handbell_arrangement(arrangement)
    assert result["valid"] is False
    assert "physical_bell_overlap" in {e["code"] for e in result["errors"]}


def test_rejects_more_than_two_simultaneous_bells_for_one_performer():
    arrangement = _arrangement()
    arrangement["events"][2].update(
        {"start_beat": 0, "duration_beats": 1, "performer_id": "P1"}
    )
    result = validate_handbell_arrangement(arrangement)
    assert result["valid"] is False
    assert "performer_exceeds_two_hands" in {e["code"] for e in result["errors"]}


@pytest.mark.parametrize("tempo", [0, 300, True, float("nan")])
def test_rejects_invalid_tempo(tempo):
    arrangement = _arrangement()
    arrangement["tempo_bpm"] = tempo
    assert "tempo_bpm_out_of_range" in {
        e["code"] for e in validate_handbell_arrangement(arrangement)["errors"]
    }


def test_reports_unverified_performance_dimensions_instead_of_overclaiming():
    result = validate_handbell_arrangement(_arrangement())
    assert "musicality" in result["not_yet_validated"]
    assert "ringing_and_damping_techniques" in result["not_yet_validated"]


def test_rejects_missing_inventory():
    arrangement = _arrangement()
    arrangement["bells"] = []
    assert "bell_inventory_required" in {
        e["code"] for e in validate_handbell_arrangement(arrangement)["errors"]
    }
