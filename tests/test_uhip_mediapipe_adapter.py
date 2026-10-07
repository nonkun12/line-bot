from pathlib import Path

import pytest

from uhip.phase0.mediapipe_camera import verify_model_sha256


def test_model_sha256_verification_rejects_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        verify_model_sha256(tmp_path / "missing.task", "a" * 64)


def test_model_sha256_verification_rejects_wrong_hash(tmp_path: Path):
    model = tmp_path / "model.task"
    model.write_bytes(b"local-test-model")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        verify_model_sha256(model, "a" * 64)


def test_model_sha256_verification_accepts_exact_hash(tmp_path: Path):
    model = tmp_path / "model.task"
    model.write_bytes(b"local-test-model")
    import hashlib

    expected = hashlib.sha256(model.read_bytes()).hexdigest()
    assert verify_model_sha256(model, expected) == expected
