import pytest
from core.ai_factory_stage141_evolution import Fitness
from core.ai_factory_stage150_evolution_history import EvolutionHealthReport,EvolutionTrend,GenerationObservation
from core.ai_factory_stage151_evolutionary_knowledge import EvolutionKnowledgeEngine,EvolutionKnowledgeError,StrategyKind
SUITE="a"*64
def obs(g,a,i,lat=100,mem=512):
 return GenerationObservation(g,(f"c{g}",),(Fitness(a,i,.99,lat,mem,0,SUITE),),(f"{g:064x}",),SUITE)
def health(xs,t,sa=False,ra=False):
 return EvolutionHealthReport(tuple(x.generation for x in xs),t,0,0,2 if sa else 0,2,sa,ra,SUITE)
def test_stagnation_proposes_diversification_and_suite_review():
 xs=(obs(1,.8,.8),obs(2,.8,.8),obs(3,.8,.8)); r=EvolutionKnowledgeEngine().derive(xs,health(xs,EvolutionTrend.STAGNANT,True))
 kinds={p.strategy for p in r.proposals}
 assert StrategyKind.DIVERSIFY_PARENTS in kinds and StrategyKind.REVIEW_EVALUATION_COVERAGE in kinds
 assert all(not p.execution_authorized and not p.model_mutation_authorized and not p.auto_adoption_authorized for p in r.proposals)
def test_regression_proposes_investigation():
 xs=(obs(1,.9,.9),obs(2,.8,.8)); r=EvolutionKnowledgeEngine().derive(xs,health(xs,EvolutionTrend.REGRESSING,ra=True))
 assert r.proposals[0].strategy is StrategyKind.INVESTIGATE_REGRESSION
def test_improvement_preserves_control():
 xs=(obs(1,.8,.8),obs(2,.9,.9)); r=EvolutionKnowledgeEngine().derive(xs,health(xs,EvolutionTrend.IMPROVING))
 assert r.proposals[0].strategy is StrategyKind.RETAIN_CURRENT and r.lessons[0].outcome=="improvement"
def test_rejects_health_mismatch_and_suite_drift():
 xs=(obs(1,.8,.8),obs(2,.9,.9)); bad=EvolutionHealthReport((1,),EvolutionTrend.IMPROVING,0,0,0,3,False,False,SUITE)
 with pytest.raises(EvolutionKnowledgeError): EvolutionKnowledgeEngine().derive(xs,bad)
 changed=GenerationObservation(2,("c2",),(Fitness(.9,.9,.99,100,512,0,"b"*64),),("2"*64,),"b"*64)
 h=EvolutionHealthReport((1,2),EvolutionTrend.IMPROVING,1,0,0,3,False,False,SUITE)
 with pytest.raises(EvolutionKnowledgeError): EvolutionKnowledgeEngine().derive((xs[0],changed),h)
def test_resource_pressure_proposal():
 xs=(obs(1,.8,.8,1500,5000),); r=EvolutionKnowledgeEngine().derive(xs,health(xs,EvolutionTrend.INSUFFICIENT_DATA))
 assert StrategyKind.REDUCE_RESOURCE_PRESSURE in {p.strategy for p in r.proposals}
def test_empty_history_rejected():
 with pytest.raises(EvolutionKnowledgeError): EvolutionKnowledgeEngine().derive((),health((),EvolutionTrend.INSUFFICIENT_DATA))
