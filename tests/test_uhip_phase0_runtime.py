import json

from uhip.phase0 import GatePolicy, Observation, recognize, replay_lines


def make_observation(**overrides):
    values = {
        "gesture": "thumb_up",
        "confidence_raw": 0.99,
        "confidence_calibrated": 0.97,
        "stable_frames": 8,
        "duration_ms": 160,
        "hand_count": 1,
        "in_frame": True,
        "hand_label": "right",
        "track_id": 3,
        "mirrored": True,
        "seq": 1,
        "t_mono_ns": 100,
        "device_id": "device-1",
        "session_id": "session-1",
    }
    values.update(overrides)
    return Observation(**values)


def test_recognition_gate_builds_local_universal_event_only():
    result = recognize(make_observation())
    assert result.passed is True
    assert result.reason == "accepted"
    assert result.event["modality"] == "hand"
    assert result.event["payload"]["local"] is True
    assert result.event["gate"]["recognition_passed"] is True
    assert result.event["ttl_ms"] == 500


def test_gate_fails_closed_for_multiple_hands():
    result = recognize(make_observation(hand_count=2))
    assert result.passed is False
    assert result.reason == "hand_count"
    assert result.event is None


def test_gate_fails_closed_for_low_confidence_and_unstable_tracking():
    policy = GatePolicy(min_confidence=0.90, min_stable_frames=3)
    low = recognize(make_observation(confidence_calibrated=0.50), policy)
    unstable = recognize(make_observation(stable_frames=2), policy)
    assert low.passed is False
    assert low.reason == "calibrated_confidence"
    assert unstable.passed is False
    assert unstable.reason == "unstable"
    assert low.event is None
    assert unstable.event is None


def test_replay_is_deterministic_and_fail_closed():
    source = [
        json.dumps({
            "gesture": "open_palm",
            "confidence_raw": 0.95,
            "confidence_calibrated": 0.94,
            "stable_frames": 4,
            "duration_ms": 80,
            "hand_count": 1,
            "in_frame": True,
            "hand_label": "left",
            "track_id": 9,
            "mirrored": False,
            "seq": 1,
            "t_mono_ns": 10,
            "device_id": "device-1",
            "session_id": "replay-1",
        }),
        "{bad json",
        json.dumps({
            "gesture": "fist",
            "confidence_raw": 0.89,
            "confidence_calibrated": 0.88,
            "stable_frames": 4,
            "duration_ms": 80,
            "hand_count": 1,
            "in_frame": True,
            "hand_label": "left",
            "track_id": 10,
            "mirrored": False,
            "seq": 2,
            "t_mono_ns": 20,
            "device_id": "device-1",
            "session_id": "replay-1",
        }),
    ]
    first = replay_lines(source)
    second = replay_lines(source)
    assert [(x.result.passed, x.result.reason) for x in first] == [
        (True, "accepted"),
        (False, "invalid_record:JSONDecodeError"),
        (False, "raw_confidence"),
    ]
    assert [(x.result.passed, x.result.reason) for x in first] == [
        (x.result.passed, x.result.reason) for x in second
    ]
