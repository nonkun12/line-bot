from pathlib import Path


TEMPLATE = Path("templates/camera_test.html")


def test_camera_test_page_has_mobile_camera_requirements() -> None:
    html = TEMPLATE.read_text(encoding="utf-8")
    assert 'playsinline' in html
    assert 'getUserMedia' in html
    assert 'isSecureContext' in html
    assert 'facingMode' in html


def test_camera_test_page_does_not_upload_frames() -> None:
    html = TEMPLATE.read_text(encoding="utf-8")
    assert "fetch(" not in html
    assert "XMLHttpRequest" not in html
    assert "FormData" not in html


def test_camera_test_page_stops_tracks() -> None:
    html = TEMPLATE.read_text(encoding="utf-8")
    assert "getTracks()" in html
    assert "track.stop()" in html
