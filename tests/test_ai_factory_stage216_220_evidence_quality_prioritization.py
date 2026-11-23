from core.ai_factory_stage216_220_evidence_quality_prioritization import *
def test_216_integrity_counts_and_hold():
 assert stage216_integrity(total=2,success_count=1,safety_regression_count=0,classifications=["SUCCESS_CONFIRMED","EXPECTED_FAILURE_CONFIRMED"])["status"]=="AGGREGATE_INTEGRITY_VALID"
 assert stage216_integrity(total=2,success_count=0,safety_regression_count=0,classifications=["SUCCESS_CONFIRMED","EXPECTED_FAILURE_CONFIRMED"])["status"]=="INSUFFICIENT_EVIDENCE"
 assert stage216_integrity(total=1,success_count=0,safety_regression_count=0,classifications=["SUCCESS_CONFIRMED"],held=True)["status"]=="INSUFFICIENT_EVIDENCE"
def test_217_wilson_interval_edges():
 r=stage217_wilson_interval(successes=5,total=5)
 assert 0<r["wilson_95_lower"]<1 and r["wilson_95_upper"]==1
 assert stage217_wilson_interval(successes=0,total=5)["wilson_95_lower"]==0
 assert stage217_wilson_interval(successes=6,total=5)["status"]=="INSUFFICIENT_EVIDENCE"
def test_218_coverage():
 r=stage218_coverage(required_strata=["a","b"],observed_strata={"a":3,"b":0})
 assert r["coverage_rate"]==.5 and r["missing_strata"]==["b"]
 assert stage218_coverage(required_strata=["a"],observed_strata={"a":1})["status"]=="COVERAGE_COMPLETE"
def test_219_score_clamps_and_rejects_invalid():
 assert stage219_risk_adjusted_score(success_rate=1,safety_regressions=0,coverage_rate=1,uncertainty_width=0)["score"]==1
 assert stage219_risk_adjusted_score(success_rate=1,safety_regressions=1,coverage_rate=1,uncertainty_width=0)["score"]==.5
 assert stage219_risk_adjusted_score(success_rate=2,safety_regressions=0,coverage_rate=1,uncertainty_width=0)["status"]=="INSUFFICIENT_EVIDENCE"
def test_220_recommendation_fail_closed():
 r=stage220_next_step(integrity_valid=True,lower_bound=.2,coverage_rate=1,safety_regressions=0)
 assert r["recommended_action"]=="PROPOSE_NEXT_CONTROLLED_EVALUATION"
 assert stage220_next_step(integrity_valid=False,lower_bound=.8,coverage_rate=1,safety_regressions=0)["recommended_action"]=="REPAIR_EVIDENCE_INTEGRITY"
 assert stage220_next_step(integrity_valid=True,lower_bound=.8,coverage_rate=.5,safety_regressions=0)["recommended_action"]=="COLLECT_MISSING_STRATA"
 assert stage220_next_step(integrity_valid=True,lower_bound=.8,coverage_rate=1,safety_regressions=1)["recommended_action"]=="INVESTIGATE_SAFETY_REGRESSIONS"
