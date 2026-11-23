from core.ai_factory_stage346_350_robustness_uncertainty_gates import *

def r(): return stage346_check_perturbation_robustness(reference_scores={"a":.8,"b":.7,"c":.9},perturbed_scores={"a":.82,"b":.68,"c":.91},maximum_absolute_change=.1)
def m(): return stage347_check_missingness_bounds(expected_count=100,observed_count=98,maximum_missing_share=.05)
def u(): return stage348_check_uncertainty_interval(lower_bound=.1,upper_bound=.2,minimum_precision=.7)
def c(): return stage349_check_metric_contract(declared_metrics={"quality":{"direction":"higher_is_better","unit":"score"}},observed_metrics={"quality":{"direction":"higher_is_better","unit":"score"}},required_metrics=["quality"])
def test_346_perturbation_pairs_and_bounds():
 assert r()["status"]=="PERTURBATION_ROBUSTNESS_PASSED"
 assert stage346_check_perturbation_robustness(reference_scores={"a":.1},perturbed_scores={"a":.8},maximum_absolute_change=.1)["status"]=="PERTURBATION_ROBUSTNESS_FAILED"
def test_347_missingness_is_bounded():
 assert m()["status"]=="MISSINGNESS_BOUND_PASSED"
 assert stage347_check_missingness_bounds(expected_count=10,observed_count=5,maximum_missing_share=.1)["status"]=="MISSINGNESS_BOUND_FAILED"
def test_348_interval_width():
 assert u()["status"]=="UNCERTAINTY_INTERVAL_PASSED"
 assert stage348_check_uncertainty_interval(lower_bound=0,upper_bound=1,minimum_precision=.9)["status"]=="UNCERTAINTY_INTERVAL_TOO_WIDE"
def test_349_metric_contract_exact_match():
 assert c()["status"]=="METRIC_CONTRACT_MATCHED"
 bad=stage349_check_metric_contract(declared_metrics={"quality":{"direction":"higher_is_better","unit":"score"}},observed_metrics={"quality":{"direction":"lower_is_better","unit":"score"}},required_metrics=["quality"])
 assert bad["status"]=="METRIC_CONTRACT_MISMATCH"
def test_350_sealed_integration_fail_closed():
 out=stage350_integrate_robustness_uncertainty(robustness_result=r(),missingness_result=m(),uncertainty_result=u(),metric_result=c())
 assert out["status"]=="ROBUSTNESS_UNCERTAINTY_GATE_PASSED" and out["asi_demonstrated"] is False
 forged=dict(r()); forged["score_changes"]={"a":999}
 assert stage350_integrate_robustness_uncertainty(robustness_result=forged,missingness_result=m(),uncertainty_result=u(),metric_result=c())["status"]=="INSUFFICIENT_EVIDENCE"
 assert stage350_integrate_robustness_uncertainty(robustness_result=r(),missingness_result=m(),uncertainty_result=u(),metric_result=c(),held=True)["status"]=="INSUFFICIENT_EVIDENCE"
