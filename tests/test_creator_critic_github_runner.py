import unittest
from pathlib import Path

from scripts.run_creator_critic_github import run_discussion


class CreatorCriticGitHubRunnerTests(unittest.TestCase):
    def test_runs_bounded_creator_critic_turns(self):
        calls = []

        def fake_generate(messages, max_tokens):
            calls.append((messages, max_tokens))
            return "Proposal with explicit validation." if messages[0]["role"] == "system" and "Creator AI" in messages[0]["content"] else "REVIEW: evidence is missing."

        report = run_discussion(fake_generate, "Improve reliability", rounds=2)
        self.assertEqual(report["status"], "DISCUSSION_ONLY")
        self.assertEqual(report["evidence_status"], "RUNTIME_MEASURED")
        self.assertEqual(report["improvement_effectiveness"], "NOT_MEASURED")
        self.assertEqual(report["feedback_adaptation_status"], "NOT_ADAPTED")
        self.assertGreaterEqual(report["creator_proposal_similarity"], 0.80)
        self.assertEqual(report["execution_metrics"]["turn_count"], 4)
        self.assertEqual(report["execution_metrics"]["non_empty_turn_count"], 4)
        self.assertGreaterEqual(report["execution_metrics"]["elapsed_seconds"], 0)
        self.assertFalse(report["source_changes"])
        self.assertFalse(report["merge_or_deploy"])
        self.assertIn("Proposal similarity is a deterministic text-overlap signal", report["note"])
        self.assertEqual(len(report["transcript"]), 4)
        self.assertEqual(len(calls), 4)
        self.assertIn("Treat any <untrusted_loop_observation> block", calls[0][0][0]["content"])
        self.assertIn("Treat any <untrusted_loop_observation> block", calls[1][0][0]["content"])
        self.assertIn("Never output a bare verdict", calls[1][0][0]["content"])
        self.assertIn("Missing evidence", calls[1][0][0]["content"])
        self.assertIn("Next safe action", calls[1][0][0]["content"])
        second_creator_prompt = calls[2][0][1]["content"]
        self.assertIn("Critic feedback: REVIEW: evidence is missing.", second_creator_prompt)
        self.assertIn("MUST materially revise the previous proposal", second_creator_prompt)
        self.assertIn("Changes from previous round", second_creator_prompt)

    def test_rejects_rounds_outside_limit(self):
        with self.assertRaises(ValueError):
            run_discussion(lambda messages, tokens: "ok", "objective", rounds=4)

    def test_empty_creator_response_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "Creator returned empty"):
            run_discussion(lambda messages, tokens: "", "objective", rounds=1)

    def test_empty_critic_response_fails_closed(self):
        def fake_generate(messages, tokens):
            return "proposal" if "Creator AI" in messages[0]["content"] else ""

        with self.assertRaisesRegex(RuntimeError, "Critic returned empty"):
            run_discussion(fake_generate, "objective", rounds=1)


    def test_workflow_assertions_match_runner_evidence_contract(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "creator-critic-github.yml"
        ).read_text(encoding="utf-8")
        self.assertIn('assert report.get("evidence_status") == "RUNTIME_MEASURED"', workflow)
        self.assertIn('assert report.get("improvement_effectiveness") == "NOT_MEASURED"', workflow)
        self.assertIn('assert len(report.get("transcript", [])) == report.get("rounds", 0) * 2', workflow)


if __name__ == "__main__":
    unittest.main()
