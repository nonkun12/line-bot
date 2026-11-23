from core.ai_factory_stage341_345_replication_leakage_regression import (
 stage341_check_replication_consistency,stage342_check_benchmark_partition_overlap,
 stage343_check_guardrail_noninferiority,stage344_check_evidence_source_diversity,
 stage345_integrate_replication_leakage_regression)

def replication():
 return stage341_check_replication_consistency(replication_gains={"r1":.3,"r2":.28,"r3":.32},maximum_gain_spread=.1,minimum_mean_gain=.1)
def partitions():
 return stage342_check_benchmark_partition_overlap(training_task_ids=["tr1","tr2"],evaluation_task_ids=["ev1"],holdout_task_ids=["ho1","ho2"])
def guardrails():
 return stage343_check_guardrail_noninferiority(guardrail_deltas={"safety":0.0,"latency":-.01,"quality":.02},maximum_allowed_regression=.02)
def diversity():
 return stage344_check_evidence_source_diversity(source_evidence_counts={"source_a":3,"source_b":3,"source_c":2},maximum_source_share=.5)

def test_341_replication_spread_and_mean():
 assert replication()["status"]=="REPLICATION_CONSISTENCY_PASSED"
 assert stage341_check_replication_consistency(replication_gains={"a":.8,"b":-.2,"c":.1},maximum_gain_spread=.2)["status"]=="REPLICATION_CONSISTENCY_FAILED"
def test_342_partitions_are_pairwise_disjoint():
 assert partitions()["status"]=="BENCHMARK_PARTITIONS_DISJOINT"
 assert stage342_check_benchmark_partition_overlap(training_task_ids=["x"],evaluation_task_ids=["x"],holdout_task_ids=["z"])["status"]=="BENCHMARK_PARTITION_OVERLAP"
def test_343_every_guardrail_must_meet_noninferiority_margin():
 assert guardrails()["status"]=="GUARDRAIL_NONINFERIORITY_PASSED"
 assert stage343_check_guardrail_noninferiority(guardrail_deltas={"safety":-.2,"latency":.1},maximum_allowed_regression=.05)["status"]=="GUARDRAIL_REGRESSION_DETECTED"
def test_344_source_share_is_bounded():
 assert diversity()["status"]=="EVIDENCE_SOURCE_DIVERSITY_PASSED"
 assert stage344_check_evidence_source_diversity(source_evidence_counts={"one":9,"two":1,"three":1},maximum_source_share=.6)["status"]=="EVIDENCE_SOURCE_CONCENTRATION_FAILED"
def test_345_integrated_gate_is_sealed_and_fail_closed():
 result=stage345_integrate_replication_leakage_regression(replication_result=replication(),partition_result=partitions(),guardrail_result=guardrails(),diversity_result=diversity())
 assert result["status"]=="REPLICATION_LEAKAGE_REGRESSION_PASSED" and result["asi_demonstrated"] is False
 forged=dict(partitions()); forged["overlaps"]={"training_holdout":["leak"]}
 assert stage345_integrate_replication_leakage_regression(replication_result=replication(),partition_result=forged,guardrail_result=guardrails(),diversity_result=diversity())["status"]=="INSUFFICIENT_EVIDENCE"
 assert stage345_integrate_replication_leakage_regression(replication_result=replication(),partition_result=partitions(),guardrail_result=guardrails(),diversity_result=diversity(),held=True)["status"]=="INSUFFICIENT_EVIDENCE"
