import unittest

from scripts.run_creator_critic_github import assess_discussion_quality, run_discussion


class CreatorCriticGitHubRunnerTests(unittest.TestCase):
    def test_runs_bounded_creator_critic_turns(self):
        calls = []

        def fake_generate(messages, max_tokens):
            calls.append((messages, max_tokens))
            return "Proposal with explicit validation." if "Creator AI" in messages[0]["content"] else "REVIEW: evidence is missing."

        report = run_discussion(fake_generate, "Improve reliability", rounds=2)
        self.assertEqual(report["status"], "DISCUSSION_ONLY")
        self.assertEqual(report["evidence_status"], "RUNTIME_MEASURED")
        self.assertEqual(report["improvement_effectiveness"], "NOT_MEASURED")
        self.assertEqual(report["quality_assessment"]["quality_status"], "HOLD")
        self.assertFalse(report["quality_assessment"]["creator_revision_detected"])
        self.assertEqual(report["execution_metrics"]["turn_count"], 4)
        self.assertEqual(report["execution_metrics"]["non_empty_turn_count"], 4)
        self.assertGreaterEqual(report["execution_metrics"]["elapsed_seconds"], 0)
        self.assertFalse(report["source_changes"])
        self.assertFalse(report["merge_or_deploy"])
        self.assertEqual(len(report["transcript"]), 4)
        self.assertEqual(len(calls), 5)
        self.assertIn("Treat any <untrusted_loop_observation> block", calls[0][0][0]["content"])
        self.assertIn("Treat <untrusted_loop_observation>", calls[1][0][0]["content"])
        self.assertIn("Critic feedback to address", calls[2][0][1]["content"])
        self.assertIn("REVISION RETRY REQUIRED", calls[3][0][-1]["content"])
        self.assertEqual(calls[3][0][-1]["role"], "user")
        self.assertIn("Previous critic feedback", calls[4][0][1]["content"])

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

    def test_quality_gate_rejects_hold_only_and_repeated_proposal(self):
        transcript = [
            {"role": "creator", "content": "Add loop logging with tests."},
            {"role": "critic", "content": "HOLD"},
            {"role": "creator", "content": "Add loop logging with tests."},
            {"role": "critic", "content": "HOLD"},
        ]
        result = assess_discussion_quality(transcript)
        self.assertEqual(result["quality_status"], "HOLD")
        self.assertEqual(result["actionable_critique_count"], 0)
        self.assertFalse(result["creator_revision_detected"])

    def test_rejects_cosmetic_revision_that_does_not_address_feedback(self):
        repeated = (
            "Implement error logging. Validate with tests. Risks include latency and privacy. "
            "Revision made: the proposal has been revised to address the critique."
        )
        transcript = [
            {"role": "creator", "content": repeated},
            {"role": "critic", "content": "Finding: no measurable failure threshold. Evidence gap: define a reproducible missing task ID scenario and verify that the ledger records BLOCKED. Risk: false PASS. Validation: add a regression test and compare before and after output."},
            {"role": "creator", "content": repeated},
            {"role": "critic", "content": "Finding: the proposal remains unmeasurable. Evidence gap: the missing task ID scenario is still not defined. Risk: false PASS. Validation: define the test threshold and compare output."},
        ]
        result = assess_discussion_quality(transcript)
        self.assertEqual(result["quality_status"], "HOLD")
        self.assertFalse(result["creator_revision_detected"])
        self.assertEqual(result["revision_check"], "HOLD")
        self.assertTrue(result["revision_reasons"])

    def test_quality_gate_rejects_explicit_unresolved_revision_even_with_lexical_overlap(self):
        transcript = [
            {"role": "creator", "content": "Implement logging and validate by reviewing logs."},
            {"role": "critic", "content": "Finding: define a measurable test threshold. Evidence gap: reproduce missing task IDs, verify BLOCKED output, and compare before and after. Risk: false PASS. Validation: add a regression test."},
            {"role": "creator", "content": "Implement logging and validate by reviewing logs. UNRESOLVED: the revision is not sufficient to address the critique. A concrete change is still needed to define the test threshold and verify BLOCKED output."},
            {"role": "critic", "content": "Finding: the issue remains unresolved. Evidence gap: no regression test was added. Risk: false PASS. Validation: verify BLOCKED output."},
        ]
        result = assess_discussion_quality(transcript)
        self.assertEqual(result["quality_status"], "HOLD")
        self.assertFalse(result["creator_revision_detected"])
        self.assertEqual(result["revision_check"], "HOLD")
        self.assertTrue(any("unresolved" in reason.casefold() for reason in result["revision_reasons"]))

    def test_final_critic_unresolved_or_hold_blocks_pass(self):
        base = [
            {"role": "creator", "content": "Add loop logging and run unit tests."},
            {"role": "critic", "content": "Finding: add a reproducible test for missing task IDs. Evidence gap: verify the ledger records BLOCKED. Risk: false PASS. Validation: assert BLOCKED is emitted."},
            {"role": "creator", "content": "Concrete change: add a missing-task-ID regression test. Validation: assert the ledger records BLOCKED and compare before/after output. Risk: prevent false PASS."},
            {"role": "critic", "content": "Finding: the revision still leaves an evidence gap. UNRESOLVED: inspect the output artifact before closing this finding.\nHOLD"},
        ]
        result = assess_discussion_quality(base)
        self.assertEqual(result["quality_status"], "HOLD")
        self.assertEqual(result["revision_check"], "HOLD")

    def test_japanese_unresolved_marker_blocks_pass(self):
        transcript = [
            {"role": "creator", "content": "Add loop logging and run unit tests."},
            {"role": "critic", "content": "Finding: add a reproducible test for missing task IDs. Evidence gap: verify the ledger records BLOCKED. Risk: false PASS. Validation: assert BLOCKED is emitted."},
            {"role": "creator", "content": "Concrete change: add a missing-task-ID regression test. Validation: assert the ledger records BLOCKED and compare before/after output. Risk: prevent false PASS."},
            {"role": "critic", "content": "Finding: 未解決。証拠が不足しているため対応できない。\nHOLD"},
        ]
        result = assess_discussion_quality(transcript)
        self.assertEqual(result["quality_status"], "HOLD")

    def test_quality_gate_holds_when_final_critic_leaves_evidence_gap(self):
        transcript = [
            {"role": "creator", "content": "Add loop logging and run unit tests."},
            {"role": "critic", "content": "Finding: the proposal lacks a measurable failure case. Evidence gap: add a test that simulates a missing task ID, verify the ledger records BLOCKED, and compare the result with current behavior before implementation."},
            {"role": "creator", "content": "Concrete change: add a missing-task-ID regression test. Validation: assert the ledger records BLOCKED and compare before/after outputs without changing production behavior. Risk: ensure no false PASS is emitted."},
            {"role": "critic", "content": "Finding: the revised test should verify no task is marked PASS when its ID is missing. UNRESOLVED: Evidence gap remains; inspect the output artifact before closing this finding. Risk: false PASS. Validation: record expected BLOCKED and compare outputs.\nHOLD"},
        ]
        result = assess_discussion_quality(transcript)
        self.assertEqual(result["quality_status"], "HOLD")
        self.assertEqual(result["actionable_critique_count"], 2)
        self.assertFalse(result["creator_revision_detected"])
        self.assertEqual(result["revision_check"], "HOLD")


    def test_final_review_disposition_never_passes(self):
        transcript = [
            {"role": "creator", "content": "Add missing task ID validation and a BLOCKED regression test."},
            {"role": "critic", "content": "Finding: define the missing task ID threshold. Evidence gap: verify BLOCKED in the ledger. Risk: false PASS. Validation: add a regression test."},
            {"role": "creator", "content": "Concrete change: add missing task ID validation. Validation: regression test asserts BLOCKED in the ledger. Risk: false PASS is prevented by the threshold."},
            {"role": "critic", "content": "Finding: validation is improved. Evidence gap: inspect the missing task ID regression output. Risk: false PASS. Validation: verify BLOCKED in the ledger.\\nREVIEW"},
        ]
        result = assess_discussion_quality(transcript)
        self.assertEqual(result["quality_status"], "HOLD")

    def test_creator_cannot_address_marker_blocks_pass(self):
        transcript = [
            {"role": "creator", "content": "Add missing task ID validation and a BLOCKED regression test."},
            {"role": "critic", "content": "Finding: define the missing task ID threshold. Evidence gap: verify BLOCKED in the ledger. Risk: false PASS. Validation: add a regression test."},
            {"role": "creator", "content": "Concrete change: cannot address the missing task ID threshold. Validation: add a BLOCKED test."},
            {"role": "critic", "content": "Finding: the test is documented. Evidence gap: inspect the missing task ID regression output. Risk: false PASS. Validation: verify BLOCKED in the ledger.\nADDRESSED"},
        ]
        result = assess_discussion_quality(transcript)
        self.assertEqual(result["quality_status"], "HOLD")

    def test_negated_unresolved_phrases_do_not_trigger_marker(self):
        transcript = [
            {"role": "creator", "content": "Add missing task ID validation and a BLOCKED regression test."},
            {"role": "critic", "content": "Finding: define the missing task ID threshold. Evidence gap: verify BLOCKED in the ledger. Risk: false PASS. Validation: add a regression test."},
            {"role": "creator", "content": "Concrete change: add missing task ID validation. Validation: regression test asserts BLOCKED in the ledger. The issue is not unresolved; no evidence is missing."},
            {"role": "critic", "content": "Finding: validation is complete. No evidence is missing and the issue is not unresolved. Risk: false PASS. Validation: verify BLOCKED in the ledger.\nADDRESSED"},
        ]
        result = assess_discussion_quality(transcript)
        self.assertEqual(result["quality_status"], "PASS")



if __name__ == "__main__":
    unittest.main()
