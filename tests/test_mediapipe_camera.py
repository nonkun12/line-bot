from __future__ import annotations

from types import SimpleNamespace

from uhip.phase0.mediapipe_camera import classify_landmarks, thumb_geometry_features


def point(x: float, y: float) -> SimpleNamespace:
    return SimpleNamespace(x=x, y=y)


def sample_landmarks(scale: float = 1.0) -> list[SimpleNamespace]:
    base = [
        (0.50, 0.80), (0.46, 0.72), (0.45, 0.65), (0.44, 0.59), (0.43, 0.54),
        (0.43, 0.68), (0.43, 0.61), (0.43, 0.57), (0.43, 0.53),
        (0.50, 0.64), (0.50, 0.57), (0.50, 0.51), (0.50, 0.47),
        (0.57, 0.68), (0.57, 0.61), (0.57, 0.57), (0.57, 0.53),
        (0.64, 0.70), (0.64, 0.64), (0.64, 0.60), (0.64, 0.56),
    ]
    ox, oy = base[0]
    return [point(ox + (x - ox) * scale, oy + (y - oy) * scale) for x, y in base]


def test_thumb_geometry_requires_21_landmarks() -> None:
    assert thumb_geometry_features([]) == {}
    assert classify_landmarks([]) == ("unknown", 0.0)


def test_thumb_geometry_is_scale_normalized() -> None:
    small = thumb_geometry_features(sample_landmarks(0.5))
    large = thumb_geometry_features(sample_landmarks(2.0))
    for key in ("near_index_mcp", "near_index_pip", "near_middle_pip", "reach", "tip_ip", "ip_mcp"):
        assert abs(small[key] - large[key]) < 1e-9


def test_thumb_geometry_is_diagnostic_only_for_current_classifier() -> None:
    landmarks = sample_landmarks()
    features = thumb_geometry_features(landmarks)
    assert features
    # This diagnostic helper must not itself grant or revoke a gesture.
    assert classify_landmarks(landmarks)[0] in {"unknown", "fist", "thumb_up", "open_palm"}


def test_thumb_geometry_contains_no_image_or_network_state() -> None:
    features = thumb_geometry_features(sample_landmarks())
    assert all(isinstance(key, str) for key in features)
    assert all(isinstance(value, float) for value in features.values())
