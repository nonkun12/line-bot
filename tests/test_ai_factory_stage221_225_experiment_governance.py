from core.ai_factory_stage221_225_experiment_governance import *
def test_221_selects_best_safe_gain_per_cost():
 c=[{"experiment_id":"a","objective":"x","evidence_complete":True,"safety_approved":True,"estimated_cost":2,"expected_information_gain":3},{"experiment_id":"b","objective":"y","evidence_complete":True,"safety_approved":False,"estimated_cost":1,"expected_information_gain":9}]
 assert stage221_select_experiment(candidates=c)["recommended_experiment_id"]=="a"
 assert stage221_select_experiment(candidates=c,held=True)["status"]=="INSUFFICIENT_EVIDENCE"
def test_222_cost_budget():
 assert stage222_cost_efficiency(observed_gain=2,actual_cost=4,budget=5)["gain_per_cost"]==.5
 assert stage222_cost_efficiency(observed_gain=2,actual_cost=6,budget=5)["status"]=="BUDGET_EXCEEDED"
def test_223_persistence():
 w=[{"window_id":str(i),"evidence_digest":"d"+str(i),"signature_valid":True,"gain":.1,"safety_score":.97} for i in range(3)]
 assert stage223_persistence(window_results=w)["status"]=="PERSISTENT_IMPROVEMENT_SUPPORTED"
 assert stage223_persistence(window_results=[dict(w[0],gain=-.1),*w[1:]])["status"]=="PERSISTENCE_NOT_SUPPORTED"
def test_224_regression():
 assert stage224_regression(baseline={"quality":.9,"safety":.99},current={"quality":.88,"safety":.99})["status"]=="REGRESSION_DETECTED"
 assert stage224_regression(baseline={"quality":.9,"safety":.99},current={"quality":.895,"safety":.99})["status"]=="NO_REGRESSION_DETECTED"
def test_225_independent_eval():
 assert stage225_independent_evaluation(executor_id="a",evaluator_id="b",evaluation_digest="d",signature_valid=True,rubric_version="v1")["status"]=="INDEPENDENT_EVALUATION_ATTESTED"
 assert stage225_independent_evaluation(executor_id="a",evaluator_id="a",evaluation_digest="d",signature_valid=True,rubric_version="v1")["status"]=="INSUFFICIENT_EVIDENCE"
