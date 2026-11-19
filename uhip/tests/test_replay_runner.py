from replay_runner import replay


def _valid_event(event_id: str, seq: int) -> dict:
    return {
        "event_id": event_id,
        "seq": seq,
        "gate": {"recognition_passed": True},
        "confidence": {"calibrated": 0.95},
        "ttl_ms": 500,
    }


def test_replay_rejects_duplicate_event_id_and_sequence_regression():
    events = [
        _valid_event("e1", 1),
        _valid_event("e1", 2),
        _valid_event("e2", 1),
    ]

    results = replay(events)

    assert [r.reason for r in results] == [
        "accepted",
        "duplicate_event_id",
        "sequence_regression",
    ]


def test_replay_accepts_stable_sequence():
    events = [
        _valid_event("e1", 1),
        _valid_event("e2", 2),
        _valid_event("e3", 3),
    ]

    results = replay(events)

    assert all(r.accepted for r in results)
    assert [r.reason for r in results] == ["accepted", "accepted", "accepted"]


def test_replay_fail_closed_for_negative_conditions():
    events = [
        {**_valid_event("low", 1), "confidence": {"calibrated": 0.2}},
        {**_valid_event("hands", 2), "hand_count": 2},
        {**_valid_event("people", 3), "person_count": 2},
        {**_valid_event("frame", 4), "out_of_frame": True},
        {**_valid_event("ttl", 5), "ttl_ms": 0},
    ]

    results = replay(events)

    assert [r.reason for r in results] == [
        "low_confidence",
        "multiple_hands",
        "multiple_people",
        "out_of_frame",
        "expired_ttl",
    ]
    assert not any(r.accepted for r in results)


def test_replay_fails_closed_when_recognition_gate_is_missing():
    results = replay([_valid_event("e1", 1) | {"gate": None}])

    assert results[0].accepted is False
    assert results[0].reason == "recognition_gate_failed"


def test_replay_fails_closed_for_invalid_sequence():
    results = replay([
        {"event_id": "missing-seq"},
        {"event_id": "negative-seq", "seq": -1},
    ])

    assert [r.reason for r in results] == ["invalid_sequence", "invalid_sequence"]
