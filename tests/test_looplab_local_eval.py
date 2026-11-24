import subprocess
import sys

from scripts.run_looplab_local_eval import _metrics, _score, run


def test_local_eval_baseline_only_is_deterministic_and_never_production_evidence():
    first = run(baseline_only=True)
    second = run(baseline_only=True)
    assert first == second
    assert first["status"] == "BASELINE_ONLY"
    assert first["production_evidence"] is False
    assert first["rsi_ingestion"] == "PROHIBITED_SYNTHETIC_FIXTURE"
    assert first["sample_count"] == 60
    assert first["challenger"] is None


def test_local_eval_smoke_subset_is_bounded():
    result = run(limit=3, baseline_only=True)
    assert result["sample_count"] == 3
    assert result["baseline"]["metrics"]["query_count"] == 3


def test_scoring_counts_negative_false_positives():
    rows = _score([{"id": "q1", "kind": "negative", "relevant": []}], {"q1": ["doc-a"]}, 5)
    assert rows[0]["false_positive"] is True
    assert _metrics(rows, 5)["negative_false_positive_rate"] == 1.0


def test_one_command_launcher_help_does_not_contact_model():
    result = subprocess.run(
        [sys.executable, "-m", "scripts.start_looplab_local", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert "--model" in result.stdout
