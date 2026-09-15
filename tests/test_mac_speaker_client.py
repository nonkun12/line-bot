from pathlib import Path
import subprocess


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "mac_speaker_client.sh"


def test_mac_speaker_client_exists_and_is_valid_bash():
    assert SCRIPT.is_file()
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_mac_speaker_client_uses_shared_voice_api_and_never_embeds_key():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "/api/voice/transcribe" in source
    assert "/api/voice" in source
    assert "/api/voice/speak" in source
    assert "INTERNAL_PUSH_KEY" in source
    assert "<the same server-side internal key>" not in source
