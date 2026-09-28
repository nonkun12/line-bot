from replay_runner import replay


def test_replay_rejects_duplicate_event_id_and_sequence_regression():
    events = [
        {"event_id": "e1", "seq": 1},
        {"event_id": "e1", "seq": 2},
        {"event_id": "e2", "seq": 1},
    ]

    results = replay(events)

    assert [r.reason for r in results] == [
        "accepted",
        "duplicate_event_id",
        "sequence_regression",
    ]


def test_replay_accepts_stable_sequence():
    events = [
        {"event_id": "e1", "seq": 1},
        {"event_id": "e2", "seq": 2},
        {"event_id": "e3", "seq": 3},
    ]

    results = replay(events)

    assert all(r.accepted for r in results)
    assert [r.reason for r in results] == ["accepted", "accepted", "accepted"]


def test_replay_fail_closed_for_negative_conditions():
    events = [
        {"event_id": "low", "seq": 1, "confidence": {"calibrated": 0.2}},
        {"event_id": "hands", "seq": 2, "hand_count": 2},
        {"event_id": "people", "seq": 3, "person_count": 2},
        {"event_id": "frame", "seq": 4, "out_of_frame": True},
        {"event_id": "ttl", "seq": 5, "ttl_ms": 0},
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
