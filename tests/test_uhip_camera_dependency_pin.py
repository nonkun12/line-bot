from pathlib import Path


def test_uhip_mac_camera_stack_pins_legacy_hands_api():
    path = Path(__file__).resolve().parents[1] / "requirements-uhip-mac.txt"
    lines = {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert "mediapipe==0.10.21" in lines
    assert "opencv-python==4.10.0.84" in lines
    assert "numpy<2,>=1.26" in lines
