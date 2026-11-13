import math
import unittest

from scripts.orca_recursive_self_improvement import (
    ImprovementRejected, advance, evaluate, new_cycle, start_next_cycle,
)

NOW = "2026-11-13T10:00:00Z"
REF = "a" * 64


def complete_to_reviewed():
    cycle = new_cycle(observation="test failures increased", source_refs=["run:123"], created_at=NOW)
    for stage in ("diagnosed", "proposed", "tested", "reviewed"):
        cycle = advance(cycle, expected_stage=cycle["stage"], next_stage=stage,
                        evidence_refs=[f"evidence:{stage}"])
    return cycle


class RecursiveSelfImprovementTests(unittest.TestCase):
    def test_cycle_requires_observation_evidence(self):
        with self.assertRaisesRegex(ImprovementRejected, "observation_evidence_required"):
            new_cycle(observation="failure", source_refs=[], created_at=NOW)

    def test_transitions_must_be_sequential(self):
        cycle = new_cycle(observation="failure", source_refs=["run:1"], created_at=NOW)
        with self.assertRaisesRegex(ImprovementRejected, "non_sequential_transition"):
            advance(cycle, expected_stage="observed", next_stage="proposed",
                    evidence_refs=["proposal:1"])

    def test_missing_test_or_critic_evidence_blocks_evaluation(self):
        cycle = complete_to_reviewed()
        with self.assertRaisesRegex(ImprovementRejected, "tests_not_passed"):
            evaluate(cycle, expected_stage="reviewed", tests_passed=False,
                     critic_verdict="pass", baseline_metric=1, candidate_metric=2,
                     metric_evidence_refs=["metric:1"])
        with self.assertRaisesRegex(ImprovementRejected, "independent_critic_not_passed"):
            evaluate(cycle, expected_stage="reviewed", tests_passed=True,
                     critic_verdict="unknown", baseline_metric=1, candidate_metric=2,
                     metric_evidence_refs=["metric:1"])

    def test_positive_result_is_candidate_not_execution_authorization(self):
        result = evaluate(complete_to_reviewed(), expected_stage="reviewed",
                          tests_passed=True, critic_verdict="pass",
                          baseline_metric=1, candidate_metric=2,
                          metric_evidence_refs=["metric:baseline", "metric:candidate"])
        self.assertEqual(result["decision"], "accepted_candidate")
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["auto_apply"])
        self.assertFalse(result["auto_merge"])
        self.assertFalse(result["auto_deploy"])


    def test_non_finite_metrics_are_rejected(self):
        cycle = complete_to_reviewed()
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ImprovementRejected, "metrics_invalid"):
                    evaluate(cycle, expected_stage="reviewed", tests_passed=True,
                             critic_verdict="pass", baseline_metric=1,
                             candidate_metric=value,
                             metric_evidence_refs=["metric:baseline", "metric:candidate"])

    def test_malformed_cycle_is_rejected_without_crashing(self):
        with self.assertRaisesRegex(ImprovementRejected, "cycle_invalid"):
            evaluate(None, expected_stage="reviewed", tests_passed=True,
                     critic_verdict="pass", baseline_metric=1, candidate_metric=2,
                     metric_evidence_refs=["metric:baseline", "metric:candidate"])


    def test_forged_reviewed_cycle_without_prior_evidence_is_rejected(self):
        cycle = complete_to_reviewed()
        del cycle["evidence"]["diagnosed"]
        with self.assertRaisesRegex(ImprovementRejected, "diagnosed_evidence_required"):
            evaluate(cycle, expected_stage="reviewed", tests_passed=True,
                     critic_verdict="pass", baseline_metric=1, candidate_metric=2,
                     metric_evidence_refs=["metric:baseline", "metric:candidate"])

    def test_tampered_cycle_identity_is_rejected(self):
        cycle = complete_to_reviewed()
        cycle["observation"] = "different observation"
        with self.assertRaisesRegex(ImprovementRejected, "cycle_identity_mismatch"):
            evaluate(cycle, expected_stage="reviewed", tests_passed=True,
                     critic_verdict="pass", baseline_metric=1, candidate_metric=2,
                     metric_evidence_refs=["metric:baseline", "metric:candidate"])

    def test_unsafe_flags_are_rejected_before_transition(self):
        cycle = new_cycle(observation="failure", source_refs=["run:1"], created_at=NOW)
        cycle["auto_apply"] = True
        with self.assertRaisesRegex(ImprovementRejected, "unsafe_execution_flag"):
            advance(cycle, expected_stage="observed", next_stage="diagnosed",
                    evidence_refs=["diagnosis:1"])

    def test_forged_evaluated_cycle_cannot_spawn_child(self):
        cycle = complete_to_reviewed()
        cycle["stage"] = "evaluated"
        cycle["decision"] = "accepted_candidate"
        with self.assertRaisesRegex(ImprovementRejected, "evaluated_evidence_required"):
            start_next_cycle(cycle, observation="next", source_refs=["run:2"],
                             created_at="2026-11-13T11:00:00Z")

    def test_non_improvement_is_deferred(self):
        result = evaluate(complete_to_reviewed(), expected_stage="reviewed",
                          tests_passed=True, critic_verdict="pass",
                          baseline_metric=2, candidate_metric=2,
                          metric_evidence_refs=["metric:baseline", "metric:candidate"])
        self.assertEqual(result["decision"], "deferred")

    def test_next_cycle_links_to_parent(self):
        result = evaluate(complete_to_reviewed(), expected_stage="reviewed",
                          tests_passed=True, critic_verdict="pass",
                          baseline_metric=1, candidate_metric=2,
                          metric_evidence_refs=["metric:baseline", "metric:candidate"])
        child = start_next_cycle(result, observation="new regression found",
                                 source_refs=["run:456"], created_at="2026-11-13T11:00:00Z")
        self.assertEqual(child["parent_cycle_id"], result["cycle_id"])
        self.assertEqual(child["depth"], 1)

    def test_recursion_depth_is_bounded(self):
        cycle = new_cycle(observation="root", source_refs=["run:1"], created_at=NOW)
        cycle["depth"] = 10
        cycle["stage"] = "evaluated"
        with self.assertRaisesRegex(ImprovementRejected, "recursion_depth_limit_reached"):
            start_next_cycle(cycle, observation="next", source_refs=["run:2"], created_at=NOW)


if __name__ == "__main__":
    unittest.main()
