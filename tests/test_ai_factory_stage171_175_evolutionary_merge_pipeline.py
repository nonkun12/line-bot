from dataclasses import replace
import hashlib
import pytest
from core.ai_factory_stage168_generation_survival_reexploration import CandidateFate, GenerationSurvivalProposal
from core.ai_factory_stage169_lineage_survival_ledger import EvolutionaryLineageLedgerBuilder, proposal_digest
from core.ai_factory_stage170_evolutionary_merge_strategy_adaptation import EvolutionaryMergeStrategyAdapter
from core.ai_factory_stage171_175_evolutionary_merge_pipeline import (
 ModelArtifact,Stage171CombinationPlanner,Stage172CompatibilityGate,MergeTrialEvidence,
 Stage173IndependentEvaluator,Stage174ParetoSelector,Stage175GenerationProposer,
 EvolutionaryMergePipelineError,
)
def make_strategy_plan():
 def fate(cid,st,status): return CandidateFate(cid,st,status,3,2,.02,.99,1.0,1.0,"verified")
 def proposal(gen,cohort,fates):
  p=GenerationSurvivalProposal(cohort,"b"*64,gen-1,gen,tuple(fates),(),
   sum(x.status=="SURVIVE" for x in fates),sum(x.status=="RETIRE" for x in fates),0,"0"*64)
  return replace(p,digest=proposal_digest(p))
 ledger=EvolutionaryLineageLedgerBuilder().build((
  proposal(5,"c"*64,[fate("a1","slerp","SURVIVE"),fate("a2","slerp","SURVIVE"),fate("b1","ties","REEXPLORE"),fate("c1","multi_model_orchestration","SURVIVE")]),
  proposal(6,"d"*64,[fate("a1","slerp","SURVIVE"),fate("a3","slerp","SURVIVE"),fate("b2","ties","RETIRE"),fate("c2","multi_model_orchestration","SURVIVE")]),
 ))
 return EvolutionaryMergeStrategyAdapter().build(ledger)
def artifacts(ok=True):
 return (ModelArtifact("parent-a","1"*64,"arch","2"*64,"3"*64,"safe","fp16","4"*64,"lic"),
 ModelArtifact("parent-b","5"*64,"arch" if ok else "other","2"*64,"3"*64,"safe","fp16","4"*64,"lic"))
def setup(ok=True):
 sp=make_strategy_plan()
 p=Stage171CombinationPlanner().build(sp,artifacts(ok))
 c=Stage172CompatibilityGate().assess(p,artifacts(ok))
 return p,c
def trial(cid,n,e,safety=.99,quality=.88):
 artifact="6"*64; digest=hashlib.sha256(f"{cid}:{n}:{e}".encode()).hexdigest()
 return MergeTrialEvidence(cid,artifact,"b"*64,f"trial-{n}",e,n,quality,safety,1000,2048,0,"signed",digest)
def report(p,c,ts,verify=lambda x:True):
 return Stage173IndependentEvaluator().build(p,c,ts,verify_signature=verify)
def test_full_stages_171_to_175_produce_proposal_only():
 p,c=setup(); assert len(p.combinations)>=1 and all(x.compatible for x in c)
 cid=p.combinations[0].candidate_id
 ev=report(p,c,[trial(cid,1,"e1"),trial(cid,2,"e2")]); assert ev.evaluations[0].eligible
 sel=Stage174ParetoSelector().build(ev); nxt=Stage175GenerationProposer().build(p,ev,sel)
 assert nxt.source_generation==6 and nxt.proposed_generation==7
 assert nxt.proposal_only and not nxt.generation_advance_authorized and not nxt.model_merge_authorized
 assert not nxt.weight_mutation_authorized and not nxt.model_activation_authorized and not nxt.production_switch_authorized
def test_compatibility_mismatch_blocks_parameter_evaluation():
 p,c=setup(False); assert len(c)>=1 and all(not x.compatible for x in c)
 with pytest.raises(EvolutionaryMergePipelineError,match="compatibility"):
  report(p,c,[trial(p.combinations[0].candidate_id,1,"e1"),trial(p.combinations[0].candidate_id,2,"e2")])
def test_stage173_rejects_replay_suite_drift_and_bad_signatures():
 p,c=setup(); cid=p.combinations[0].candidate_id; t=trial(cid,1,"e1")
 with pytest.raises(EvolutionaryMergePipelineError,match="replayed"): report(p,c,[t,t])
 with pytest.raises(EvolutionaryMergePipelineError,match="suite drift"): report(p,c,[replace(t,evaluation_suite_digest="e"*64),trial(cid,2,"e2")])
 with pytest.raises(EvolutionaryMergePipelineError,match="signature"): report(p,c,[t,trial(cid,2,"e2")],verify=lambda x:False)
def test_repeats_require_distinct_evaluators_and_quality_safety():
 p,c=setup(); cid=p.combinations[0].candidate_id
 with pytest.raises(EvolutionaryMergePipelineError,match="distinct evaluator"): report(p,c,[trial(cid,1,"same"),trial(cid,2,"same")])
 ev=report(p,c,[trial(cid,1,"e1",safety=.8),trial(cid,2,"e2",safety=.8)])
 assert not ev.evaluations[0].eligible and not Stage174ParetoSelector().build(ev).selected_for_next_trial
@pytest.mark.parametrize("stage",["171","172","173","174","175"])
def test_hold_blocks_each_stage(stage):
 p,c=setup(); cid=p.combinations[0].candidate_id; ts=[trial(cid,1,"e1"),trial(cid,2,"e2")]
 with pytest.raises(EvolutionaryMergePipelineError):
  if stage=="171": Stage171CombinationPlanner().build(make_strategy_plan(),artifacts(),hold_active=True)
  elif stage=="172": Stage172CompatibilityGate().assess(p,artifacts(),hold_active=True)
  elif stage=="173": Stage173IndependentEvaluator().build(p,c,ts,verify_signature=lambda x:True,hold_active=True)
  elif stage=="174": Stage174ParetoSelector().build(report(p,c,ts),hold_active=True)
  else:
   ev=report(p,c,ts); sel=Stage174ParetoSelector().build(ev)
   Stage175GenerationProposer().build(p,ev,sel,hold_active=True)
def test_generation_proposal_rejects_cross_stage_lineage():
 p,c=setup(); cid=p.combinations[0].candidate_id; ev=report(p,c,[trial(cid,1,"e1"),trial(cid,2,"e2")]); sel=Stage174ParetoSelector().build(ev)
 with pytest.raises(EvolutionaryMergePipelineError,match="lineage"):
  Stage175GenerationProposer().build(replace(p,digest="f"*64),ev,sel)
def test_stage171_never_creates_orchestration_weight_candidate():
 p,_=setup(); assert all(x.strategy_class=="PARAMETER_MERGE" for x in p.combinations)
