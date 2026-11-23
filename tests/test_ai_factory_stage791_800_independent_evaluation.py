import hashlib
import unittest

from core.ai_factory_stage791_800_independent_evaluation import (
    digest_record, evaluate_stages_791_800, compare_metric_sets,
)


class IndependentEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.artifact = b"reproducible benchmark output"
        self.manifest = {
            "schema_version": "1",
            "run_id": "run-001",
            "source_revision": "abc123",
            "artifacts": {"result.bin": hashlib.sha256(self.artifact).hexdigest()},
        }
        self.md = digest_record(self.manifest)
        self.attestation = {
            "evaluator_id": "evaluator-A",
            "organization": "external-lab",
            "conflict_declaration": "none_declared",
            "scope": "independent_evaluation",
            "issued_at": "2026-01-01T00:00:00Z",
            "evidence_digest": self.md,
        }
        self.reproduction = {
            "manifest_digest": self.md,
            "status": "completed",
            "environment_fingerprint": "python-linux-x86_64",
            "output_digest": hashlib.sha256(self.artifact).hexdigest(),
            "exit_code": 0,
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:01:00Z",
        }
        self.review = {
            "status": "reviewed",
            "evidence_digest": self.md,
            "conflict_declaration": "none_declared",
            "reviewer_id": "reviewer-B",
        }

    def evaluate(self, **overrides):
        args = dict(
            manifest=self.manifest,
            artifacts={"result.bin": self.artifact},
            attestation=self.attestation,
            reproduction=self.reproduction,
            baseline_metrics={"accuracy": 0.8, "latency": 100.0},
            candidate_metrics={"accuracy": 0.82, "latency": 90.0},
            metric_directions={"accuracy": "higher", "latency": "lower"},
            independent_review=self.review,
        )
        args.update(overrides)
        return evaluate_stages_791_800(**args)

    def test_valid_evidence_reaches_external_review_only(self):
        result = self.evaluate()
        self.assertEqual(result.status, "READY_FOR_EXTERNAL_AUTHENTICATED_REVIEW")
        self.assertEqual(result.stages, tuple(range(791, 801)))

    def test_artifact_tampering_blocks(self):
        result = self.evaluate(artifacts={"result.bin": b"tampered"})
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("artifact_digest_mismatch:result.bin", result.reasons)

    def test_missing_inventory_blocks(self):
        result = self.evaluate(artifacts={})
        self.assertIn("artifact_inventory_mismatch", result.reasons)

    def test_manifest_schema_and_provenance_required(self):
        manifest = dict(self.manifest, schema_version="2", run_id="")
        result = self.evaluate(manifest=manifest)
        self.assertIn("manifest_schema_unsupported", result.reasons)
        self.assertIn("manifest_provenance_incomplete", result.reasons)

    def test_attestation_binding_required(self):
        attestation = dict(self.attestation, evidence_digest="0" * 64)
        result = self.evaluate(attestation=attestation)
        self.assertIn("attestation_manifest_binding_mismatch", result.reasons)

    def test_reproduction_must_be_successful(self):
        receipt = dict(self.reproduction, exit_code=2, status="failed")
        result = self.evaluate(reproduction=receipt)
        self.assertIn("reproduction_not_completed", result.reasons)
        self.assertIn("reproduction_exit_code_not_zero", result.reasons)

    def test_reviewer_must_be_distinct(self):
        review = dict(self.review, reviewer_id="evaluator-A")
        result = self.evaluate(independent_review=review)
        self.assertIn("evaluator_and_reviewer_not_distinct", result.reasons)

    def test_conflicted_reviewer_blocks(self):
        review = dict(self.review, conflict_declaration="conflict_declared")
        result = self.evaluate(independent_review=review)
        self.assertIn("independent_review_conflict_or_missing", result.reasons)

    def test_metric_key_mismatch_blocks(self):
        errors, deltas = compare_metric_sets(
            {"a": 1}, {"b": 2}, {"a": "higher"})
        self.assertEqual(errors, ["metric_keys_mismatch"])
        self.assertEqual(deltas, {})

    def test_non_finite_metrics_block(self):
        errors, _ = compare_metric_sets(
            {"a": float("nan")}, {"a": 2}, {"a": "higher"})
        self.assertIn("metric_non_finite_or_non_numeric:a", errors)

    def test_invalid_metric_direction_blocks(self):
        errors, _ = compare_metric_sets({"a": 1}, {"a": 2}, {"a": "up"})
        self.assertIn("metric_direction_invalid:a", errors)

    def test_unreviewed_evidence_blocks(self):
        review = dict(self.review, status="pending")
        result = self.evaluate(independent_review=review)
        self.assertIn("independent_review_incomplete", result.reasons)


if __name__ == "__main__":
    unittest.main()
