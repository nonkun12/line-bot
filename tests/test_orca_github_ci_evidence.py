import unittest

from scripts.orca_github_ci_evidence import (
    EvidenceRejected, normalize_workflow_run, summarize_workflow_runs,
)

SHA = "a" * 40


def run(run_id=123, status="completed", conclusion="failure"):
    return {
        "id": run_id, "workflow_id": 77, "name": "CI", "event": "pull_request",
        "status": status, "conclusion": conclusion, "head_sha": SHA,
    }


def jobs(job_id=456, conclusion="failure"):
    return {"jobs": [{
        "id": job_id, "name": "pytest", "status": "completed",
        "conclusion": conclusion,
    }]}


class GitHubActionsEvidenceTests(unittest.TestCase):
    def test_failure_has_immutable_run_and_sha_references(self):
        result = normalize_workflow_run(run(), jobs())
        self.assertEqual(result["source"]["workflow_run_id"], 123)
        self.assertEqual(result["source"]["head_sha"], SHA)
        self.assertEqual(result["source"]["workflow_run_url"], "actions/runs/123")
        self.assertEqual(result["failed_job_names"], ["pytest"])
        self.assertIsNotNone(result["failure_signature"])

    def test_same_failure_signature_survives_new_run_and_commit(self):
        first = normalize_workflow_run(run(123), jobs())
        second_run = run(124)
        second_run["head_sha"] = "b" * 40
        second = normalize_workflow_run(second_run, jobs(457))
        self.assertEqual(first["failure_signature"], second["failure_signature"])

    def test_success_has_no_failure_signature(self):
        result = normalize_workflow_run(run(conclusion="success"), jobs(conclusion="success"))
        self.assertEqual(result["failed_job_names"], [])
        self.assertIsNone(result["failure_signature"])

    def test_in_progress_run_is_marked_incomplete(self):
        result = normalize_workflow_run(
            run(status="in_progress", conclusion=None),
            {"jobs": [{"id": 456, "name": "pytest", "status": "in_progress", "conclusion": None}]},
        )
        self.assertEqual(result["evidence_status"], "incomplete")

    def test_missing_jobs_blocks_collection(self):
        with self.assertRaisesRegex(EvidenceRejected, "workflow_jobs_evidence_missing"):
            summarize_workflow_runs([run()], {})

    def test_invalid_sha_is_rejected(self):
        bad = run()
        bad["head_sha"] = "not-a-sha"
        with self.assertRaisesRegex(EvidenceRejected, "head_sha_invalid"):
            normalize_workflow_run(bad, jobs())

    def test_boolean_run_id_is_rejected(self):
        with self.assertRaisesRegex(EvidenceRejected, "workflow_run_id_invalid"):
            normalize_workflow_run(run(True), jobs())

    def test_duplicate_failures_are_counted_by_stable_signature(self):
        second = run(124)
        summary = summarize_workflow_runs(
            [run(), second], {"123": jobs(), "124": jobs(457)},
        )
        self.assertEqual(summary["runs_observed"], 2)
        self.assertEqual(list(summary["failure_signature_counts"].values()), [2])


if __name__ == "__main__":
    unittest.main()
