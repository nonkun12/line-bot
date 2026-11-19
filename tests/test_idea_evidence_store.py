from __future__ import annotations

import os

import pytest

from core.idea_evidence import ExperimentEvidence
from core.idea_evidence_store import append_evidence_record, load_evidence_records


def sample(**overrides):
    values = {
        "experiment_id": "exp-001",
        "hypothesis_id": "hyp-001",
        "style": "recombine",
        "measured_value": 12.5,
        "evidence_refs": ("artifact:sha256:abc",),
        "code_revision": "a" * 40,
        "environment": "linux;python=3.x",
        "verification_status": "pending",
        "verified_by": "",
    }
    values.update(overrides)
    return ExperimentEvidence(**values)


def test_append_and_reload_round_trip(tmp_path):
    path = tmp_path / "evidence.jsonl"
    saved = append_evidence_record(path, sample())
    loaded = load_evidence_records(path)
    assert saved == loaded
    assert path.stat().st_mode & 0o777 == 0o600


def test_rejects_duplicate_experiment_ids(tmp_path):
    path = tmp_path / "evidence.jsonl"
    append_evidence_record(path, sample())
    with pytest.raises(ValueError, match="already exists"):
        append_evidence_record(path, sample())


def test_rejects_symlink_store(tmp_path):
    target = tmp_path / "target.jsonl"
    target.write_text("")
    link = tmp_path / "link.jsonl"
    link.symlink_to(target)
    with pytest.raises(OSError):
        load_evidence_records(link)


def test_rejects_non_private_existing_file(tmp_path):
    path = tmp_path / "public.jsonl"
    path.write_text("")
    path.chmod(0o644)
    with pytest.raises(PermissionError, match="permissions"):
        load_evidence_records(path)


def test_rejects_corrupt_jsonl(tmp_path):
    path = tmp_path / "broken.jsonl"
    path.write_text("{broken}\n")
    path.chmod(0o600)
    with pytest.raises(ValueError, match="invalid evidence record"):
        load_evidence_records(path)


def test_rejects_non_regular_store(tmp_path):
    path = tmp_path / "directory"
    path.mkdir()
    with pytest.raises(ValueError, match="regular file"):
        load_evidence_records(path)


def test_does_not_create_missing_parent_directory(tmp_path):
    path = tmp_path / "missing" / "evidence.jsonl"
    with pytest.raises(FileNotFoundError):
        append_evidence_record(path, sample())
    assert not path.parent.exists()
