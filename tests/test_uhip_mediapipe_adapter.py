from types import SimpleNamespace

from uhip.phase0.mediapipe_camera import classify_landmarks


def landmark(x: float, y: float):
    return SimpleNamespace(x=x, y=y)


def hand_landmarks(*, thumb: str, fingers: tuple[bool, bool, bool, bool]):
    points = [landmark(0.5, 0.8) for _ in range(21)]
    points[5] = landmark(0.42, 0.65)
    points[9] = landmark(0.50, 0.60)
    points[13] = landmark(0.58, 0.65)
    points[17] = landmark(0.64, 0.72)
    points[4] = landmark(0.5, 0.2 if thumb == "up" else 0.7)
    points[3] = landmark(0.5, 0.5)
    finger_pairs = [(8, 6), (12, 10), (16, 14), (20, 18)]
    for (tip, pip), is_extended in zip(finger_pairs, fingers):
        points[pip] = landmark(0.5, 0.5)
        points[tip] = landmark(0.5, 0.2 if is_extended else 0.55)
    return points


def test_classifier_accepts_open_palm():
    gesture, confidence = classify_landmarks(
        hand_landmarks(thumb="up", fingers=(True, True, True, True))
    )
    assert gesture == "open_palm"
    assert confidence >= 0.90


def test_classifier_accepts_thumb_up():
    gesture, confidence = classify_landmarks(
        hand_landmarks(thumb="up", fingers=(False, False, False, False))
    )
    assert gesture == "thumb_up"
    assert confidence >= 0.90


def test_classifier_accepts_fist():
    gesture, confidence = classify_landmarks(
        hand_landmarks(thumb="down", fingers=(False, False, False, False))
    )
    assert gesture == "fist"
    assert confidence >= 0.90


def test_classifier_fails_closed_for_ambiguous_geometry():
    gesture, confidence = classify_landmarks(
        hand_landmarks(thumb="down", fingers=(True, False, True, False))
    )
    assert gesture == "unknown"
    assert confidence == 0.0
