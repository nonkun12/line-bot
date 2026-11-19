from __future__ import annotations

import os

import pytest

from dataclasses import replace

from core.idea_evidence import ExperimentEvidence, sign_evidence_record
from core.idea_evidence_store import ExperimentEvidenceStore


def sample_record():
    return ExperimentEvidence(
        experiment_id="persisted-001",
        hypothesis_id="hyp-001",
        style="recombine",
        measured_value=12.5,
        evidence_refs=("artifact:sha256:abc",),
        code_revision="a" * 40,
        environment="python=3.x",
        verification_status="pending",
    )


def test_store_round_trips_append_only_records(tmp_path):
    store = ExperimentEvidenceStore(tmp_path / "evidence.sqlite3")
    record = sample_record()

    store.append(record)

    assert store.list_for_hypothesis("hyp-001") == (record,)
    with pytest.raises(ValueError, match="already exists"):
        store.append(record)


def test_store_separates_hypotheses_and_preserves_review_state(tmp_path):
    store = ExperimentEvidenceStore(tmp_path / "evidence.sqlite3")
    pending = sample_record()
    verified = ExperimentEvidence(
        experiment_id="persisted-002",
        hypothesis_id="hyp-002",
        style="reframe",
        measured_value=9.0,
        evidence_refs=("artifact:sha256:def",),
        code_revision="b" * 40,
        environment="python=3.x",
        verification_status="verified",
        verified_by="review-42",
    )
    reviewer_key = b"store-test-reviewer-key-material-32-bytes"
    verified = replace(
        verified,
        verification_signature=sign_evidence_record(verified, reviewer_key),
    )
    store.append(pending)
    store.append(verified)

    assert store.list_for_hypothesis("hyp-001") == (pending,)
    assert store.list_for_hypothesis("hyp-002") == (verified,)


def test_store_rejects_symlink_database_path(tmp_path):
    target = tmp_path / "real.sqlite3"
    target.touch()
    link = tmp_path / "linked.sqlite3"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="symlink"):
        ExperimentEvidenceStore(link)


def test_store_requires_existing_parent_and_persistent_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        ExperimentEvidenceStore(tmp_path / "missing" / "evidence.sqlite3")
    with pytest.raises(ValueError):
        ExperimentEvidenceStore(":memory:")
