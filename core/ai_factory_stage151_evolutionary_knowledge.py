"""Stage 151: evidence-bound evolutionary knowledge and strategy proposals."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import hashlib, json, re
from typing import Sequence
from .ai_factory_stage141_evolution import Fitness, dominates
from .ai_factory_stage150_evolution_history import EvolutionHealthReport, EvolutionTrend, GenerationObservation

class StrategyKind(str, Enum):
    RETAIN_CURRENT="retain_current"
    DIVERSIFY_PARENTS="diversify_parents"
    REVIEW_EVALUATION_COVERAGE="review_evaluation_coverage"
    REDUCE_RESOURCE_PRESSURE="reduce_resource_pressure"
    INVESTIGATE_REGRESSION="investigate_regression"

@dataclass(frozen=True)
class EvolutionLesson:
    lesson_id:str
    source_generations:tuple[int,...]
    source_evidence_digests:tuple[str,...]
    evaluation_suite_digest:str
    outcome:str
    lesson:str

@dataclass(frozen=True)
class EvolutionStrategyProposal:
    proposal_id:str
    strategy:StrategyKind
    rationale:str
    supporting_lesson_ids:tuple[str,...]
    source_generations:tuple[int,...]
    evaluation_suite_digest:str
    priority:int
    execution_authorized:bool=False
    model_mutation_authorized:bool=False
    auto_adoption_authorized:bool=False

@dataclass(frozen=True)
class EvolutionKnowledgeSnapshot:
    lessons:tuple[EvolutionLesson,...]
    proposals:tuple[EvolutionStrategyProposal,...]
    source_generation_count:int
    digest:str

class EvolutionKnowledgeError(ValueError): pass

class EvolutionKnowledgeEngine:
    def __init__(self, *, max_lessons:int=512, max_proposals:int=16):
        if not isinstance(max_lessons,int) or isinstance(max_lessons,bool) or not 1<=max_lessons<=4096: raise ValueError("max_lessons must be 1..4096")
        if not isinstance(max_proposals,int) or isinstance(max_proposals,bool) or not 1<=max_proposals<=64: raise ValueError("max_proposals must be 1..64")
        self.max_lessons=max_lessons; self.max_proposals=max_proposals

    def derive(self, observations:Sequence[GenerationObservation], health:EvolutionHealthReport)->EvolutionKnowledgeSnapshot:
        if not isinstance(health,EvolutionHealthReport) or not isinstance(observations,Sequence) or not observations:
            raise EvolutionKnowledgeError("typed health report and non-empty generation history required")
        if len(observations)>self.max_lessons or any(not isinstance(x,GenerationObservation) for x in observations):
            raise EvolutionKnowledgeError("history exceeds bounds or contains untyped observations")
        ordered=tuple(sorted(observations,key=lambda x:x.generation))
        gens=tuple(x.generation for x in ordered)
        suites={x.evaluation_suite_digest for x in ordered}
        if len(set(gens))!=len(gens) or len(suites)!=1: raise EvolutionKnowledgeError("duplicate generations or suite drift")
        suite=next(iter(suites))
        if not re.fullmatch(r"[0-9a-f]{64}",suite) or health.observed_generations!=gens or health.comparable_suite_digest!=suite:
            raise EvolutionKnowledgeError("health report does not bind exact frozen history")
        lessons=[]; proposals=[]
        def add_lesson(pair,outcome,description):
            evidence=tuple(sorted(d for x in pair for d in x.evidence_digests))
            if not evidence or any(not re.fullmatch(r"[0-9a-f]{64}",d) for d in evidence): raise EvolutionKnowledgeError("invalid source evidence digest")
            payload={"g":[x.generation for x in pair],"e":evidence,"s":suite,"o":outcome,"l":description}
            lid=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
            lessons.append(EvolutionLesson(lid,tuple(x.generation for x in pair),evidence,suite,outcome,description)); return lid
        def add_proposal(kind,rationale,ids,priority):
            payload={"k":kind.value,"r":rationale,"l":tuple(ids),"g":gens,"s":suite}
            pid=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
            proposals.append(EvolutionStrategyProposal(pid,kind,rationale,tuple(ids),gens,suite,priority))
        improve=[]; regress=[]; stagnant=[]
        for prev,cur in zip(ordered,ordered[1:]):
            if any(dominates(n,b) for n in cur.fitnesses for b in prev.fitnesses):
                improve.append(add_lesson((prev,cur),"improvement","Current generation Pareto-dominates at least one prior candidate."))
            elif all(any(dominates(b,n) for b in prev.fitnesses) for n in cur.fitnesses):
                regress.append(add_lesson((prev,cur),"regression","Every current candidate is Pareto-dominated by a prior candidate."))
            else: stagnant.append(add_lesson((prev,cur),"stagnation","No strict Pareto improvement or uniform regression observed."))
        fallback=tuple(x.lesson_id for x in lessons[-1:])
        if health.trend is EvolutionTrend.REGRESSING or health.regression_alert:
            add_proposal(StrategyKind.INVESTIGATE_REGRESSION,"Inspect signed evaluation evidence and isolate regressing metrics before another experiment.",regress or fallback,100)
        elif health.stagnation_alert or health.trend is EvolutionTrend.STAGNANT:
            add_proposal(StrategyKind.DIVERSIFY_PARENTS,"Propose a distinct bounded parent combination; compare on the unchanged suite.",stagnant or fallback,90)
            add_proposal(StrategyKind.REVIEW_EVALUATION_COVERAGE,"Review failure-mode coverage; any suite revision starts a separately versioned history.",stagnant or fallback,80)
        elif health.trend is EvolutionTrend.IMPROVING:
            add_proposal(StrategyKind.RETAIN_CURRENT,"Preserve the successful strategy as a control and test alternatives separately.",improve or fallback,70)
        else: add_proposal(StrategyKind.REVIEW_EVALUATION_COVERAGE,"Collect more independently verified generations before changing strategy.",fallback,60)
        latest=ordered[-1]
        best=sorted(latest.fitnesses,key=lambda f:(-f.accuracy,-f.instruction_following,-f.safety,f.latency_ms,f.memory_mb))[0]
        if best.latency_ms>1000 or best.memory_mb>4096:
            add_proposal(StrategyKind.REDUCE_RESOURCE_PRESSURE,"Investigate smaller local candidates without weakening safety gates.",fallback,75)
        proposals=tuple(sorted(proposals,key=lambda x:(-x.priority,x.proposal_id))[:self.max_proposals])
        payload={"lessons":[x.lesson_id for x in lessons],"proposals":[x.proposal_id for x in proposals],"g":gens,"s":suite}
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        return EvolutionKnowledgeSnapshot(tuple(lessons[-self.max_lessons:]),proposals,len(ordered),digest)

__all__=["StrategyKind","EvolutionLesson","EvolutionStrategyProposal","EvolutionKnowledgeSnapshot","EvolutionKnowledgeError","EvolutionKnowledgeEngine"]
