from dataclasses import dataclass

from uhip.phase0.camera_adapter import (
    CameraAdapter,
    CameraFrame,
    ClassifiedHand,
    bounded_frames,
)


@dataclass
class FakeSource:
    values: list[CameraFrame]

    def frames(self):
        yield from self.values


@dataclass
class FakeClassifier:
    classified: ClassifiedHand

    def classify(self, frame):
        return self.classified


def frame(frame_id: int = 1, mono_ns: int = 100):
    return CameraFrame(
        frame_id=frame_id,
        captured_mono_ns=mono_ns,
        width=640,
        height=480,
        data=None,
    )


def hand(**overrides):
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
    }
    values.update(overrides)
    return ClassifiedHand(**values)


def test_camera_adapter_routes_classifier_output_through_recognition_gate():
    adapter = CameraAdapter(
        source=FakeSource([frame()]),
        classifier=FakeClassifier(hand()),
        device_id="mac-1",
        session_id="session-1",
        engine="fake-local",
        engine_version="0.1",
        model_sha256="a" * 64,
    )
    result = list(adapter.run())
    assert len(result) == 1
    assert result[0].passed is True
    assert result[0].event["source"]["sensor"] == "camera"
    assert result[0].event["source"]["engine"] == "fake-local"
    assert result[0].event["device_id"] == "mac-1"


def test_camera_adapter_cannot_bypass_gate_on_low_confidence():
    adapter = CameraAdapter(
        source=FakeSource([frame()]),
        classifier=FakeClassifier(hand(confidence_raw=0.2)),
        device_id="mac-1",
        session_id="session-1",
        engine="fake-local",
        engine_version="0.1",
        model_sha256="a" * 64,
    )
    result = list(adapter.run())
    assert result[0].passed is False
    assert result[0].event is None


def test_bounded_frames_stops_processing_after_limit():
    values = [frame(i, i * 100) for i in range(4)]
    assert [item.frame_id for item in bounded_frames(values, max_frames=2)] == [0, 1]


def test_bounded_frames_rejects_invalid_limit():
    try:
        list(bounded_frames([], max_frames=0))
    except ValueError as exc:
        assert str(exc) == "max_frames must be >= 1"
    else:
        raise AssertionError("expected ValueError")
