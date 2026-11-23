from core.ai_factory_stage336_340_protocol_calibration_freshness import (
 stage336_check_protocol_commitment, stage337_check_evaluator_agreement,
 stage338_check_calibration_bins, stage339_check_evidence_freshness,
 stage340_integrate_protocol_calibration)

def protocol():
 return stage336_check_protocol_commitment(declared_protocol={"metric":"gain","version":1,"split":"holdout"},
  observed_protocol={"metric":"gain","version":1,"split":"holdout"},required_fields=["metric","version","split"])
def agreement():
 return stage337_check_evaluator_agreement(task_evaluator_scores={f"t{i}":{"a":.7,"b":.75,"c":.72} for i in range(3)},maximum_task_score_range=.1)
def calibration():
 return stage338_check_calibration_bins(bins=[{"count":10,"mean_confidence":.8,"observed_accuracy":.82},{"count":8,"mean_confidence":.6,"observed_accuracy":.62}],maximum_calibration_error=.05)
def freshness():
 return stage339_check_evidence_freshness(evidence_timestamps={"protocol":900,"scores":950},reference_timestamp=1000,maximum_age_seconds=200)

def test_336_protocol_commitment_detects_mismatch_and_missing_fields():
 assert protocol()["status"]=="PROTOCOL_COMMITMENT_MATCHED"
 assert stage336_check_protocol_commitment(declared_protocol={"metric":"gain"},observed_protocol={"metric":"loss"},required_fields=["metric"])["status"]=="PROTOCOL_COMMITMENT_MISMATCH"
 assert stage336_check_protocol_commitment(declared_protocol={},observed_protocol={},required_fields=["metric"])["status"]=="INSUFFICIENT_EVIDENCE"

def test_337_evaluator_agreement_bounds_task_level_range():
 assert agreement()["status"]=="EVALUATOR_AGREEMENT_PASSED"
 assert stage337_check_evaluator_agreement(task_evaluator_scores={"a":{"x":0,"y":1},"b":{"x":0,"y":1},"c":{"x":0,"y":1}},maximum_task_score_range=.2)["status"]=="EVALUATOR_AGREEMENT_FAILED"

def test_338_calibration_is_count_weighted_and_fail_closed():
 assert calibration()["status"]=="CALIBRATION_BINS_PASSED"
 assert stage338_check_calibration_bins(bins=[{"count":5,"mean_confidence":.9,"observed_accuracy":.2}])["status"]=="CALIBRATION_BINS_FAILED"
 assert stage338_check_calibration_bins(bins=[{"count":1,"mean_confidence":.9,"observed_accuracy":.9}],minimum_bin_count=5)["status"]=="INSUFFICIENT_EVIDENCE"

def test_339_freshness_rejects_old_and_future_evidence():
 assert freshness()["status"]=="EVIDENCE_FRESHNESS_PASSED"
 assert stage339_check_evidence_freshness(evidence_timestamps={"old":1},reference_timestamp=1000,maximum_age_seconds=10)["status"]=="EVIDENCE_FRESHNESS_FAILED"
 assert stage339_check_evidence_freshness(evidence_timestamps={"future":1001},reference_timestamp=1000,maximum_age_seconds=10)["status"]=="INSUFFICIENT_EVIDENCE"

def test_340_integrated_gate_requires_sealed_evidence_and_keeps_proposal_only():
 result=stage340_integrate_protocol_calibration(protocol_result=protocol(),agreement_result=agreement(),calibration_result=calibration(),freshness_result=freshness())
 assert result["status"]=="PROTOCOL_CALIBRATION_FRESHNESS_PASSED" and result["asi_demonstrated"] is False
 forged=dict(agreement()); forged["maximum_observed_range"]=999
 assert stage340_integrate_protocol_calibration(protocol_result=protocol(),agreement_result=forged,calibration_result=calibration(),freshness_result=freshness())["status"]=="INSUFFICIENT_EVIDENCE"
 assert stage340_integrate_protocol_calibration(protocol_result=protocol(),agreement_result=agreement(),calibration_result=calibration(),freshness_result=freshness(),held=True)["status"]=="INSUFFICIENT_EVIDENCE"
