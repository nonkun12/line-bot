"""Stages 171-175: bounded, evidence-bound evolutionary model-merge proposals."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib, json, math, re
from typing import Callable, Sequence
from .ai_factory_stage170_evolutionary_merge_strategy_adaptation import _plan_digest

_HEX=re.compile(r"^[0-9a-f]{64}$")
_ID=re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_PARAMETER={"slerp","ties","dare","task_arithmetic","lora","parameter_merge"}
_ORCHESTRATION={"multi_model_orchestration"}

class EvolutionaryMergePipelineError(ValueError):
    """Invalid lineage, evidence, compatibility, or safety state."""

def _hash(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
def _digest(value,label):
    if not isinstance(value,str) or not _HEX.fullmatch(value):
        raise EvolutionaryMergePipelineError(f"{label} digest invalid")

@dataclass(frozen=True)
class ModelArtifact:
    model_id:str; artifact_digest:str; architecture:str; tokenizer_digest:str
    tensor_schema_digest:str; model_format:str; quantization:str
    provenance_digest:str; license_id:str

@dataclass(frozen=True)
class MergeCombination:
    candidate_id:str; strategy:str; strategy_class:str; parent_model_ids:tuple[str,...]
    parent_artifact_digests:tuple[str,...]; allocation_share:float; digest:str

@dataclass(frozen=True)
class CombinationPlan:
    source_strategy_plan_digest:str; source_generation:int; evaluation_suite_digest:str
    combinations:tuple[MergeCombination,...]; digest:str
    proposal_only:bool=True; model_merge_authorized:bool=False; weight_mutation_authorized:bool=False

class Stage171CombinationPlanner:
    """Derives bounded candidate pairs from Stage 170; orchestration never enters tensor merge."""
    def build(self,strategy_plan,artifacts:Sequence[ModelArtifact],*,hold_active=False,kill_switch_active=False,max_combinations=32):
        if hold_active or kill_switch_active: raise EvolutionaryMergePipelineError("HOLD or kill switch blocks Stage 171")
        if not getattr(strategy_plan,"proposal_only",False) or getattr(strategy_plan,"model_merge_authorized",True) or getattr(strategy_plan,"weight_mutation_authorized",True) or getattr(strategy_plan,"generation_advanced",True):
            raise EvolutionaryMergePipelineError("unsafe Stage 170 strategy plan")
        _digest(strategy_plan.digest,"strategy plan"); _digest(strategy_plan.evaluation_suite_digest,"suite")
        expected=_plan_digest(strategy_plan.source_ledger_digest,strategy_plan.evaluation_suite_digest,
            strategy_plan.source_generation,strategy_plan.target_generation,strategy_plan.allocations,
            strategy_plan.parameter_merge_share,strategy_plan.orchestration_share,strategy_plan.exploration_share)
        if expected!=strategy_plan.digest or strategy_plan.target_generation!=strategy_plan.source_generation+1:
            raise EvolutionaryMergePipelineError("Stage 170 strategy plan digest or generation lineage mismatch")
        if not isinstance(max_combinations,int) or isinstance(max_combinations,bool) or not 1<=max_combinations<=128:
            raise EvolutionaryMergePipelineError("combination bound invalid")
        if not isinstance(artifacts,Sequence) or not 2<=len(artifacts)<=64: raise EvolutionaryMergePipelineError("two to 64 artifacts required")
        byid={}
        for a in artifacts:
            if not isinstance(a,ModelArtifact) or not _ID.fullmatch(a.model_id or ""): raise EvolutionaryMergePipelineError("typed artifact metadata required")
            _digest(a.artifact_digest,"artifact")
            if a.model_id in byid: raise EvolutionaryMergePipelineError("duplicate model identity")
            byid[a.model_id]=a
        rows=[]
        ordered=sorted(byid.values(),key=lambda a:a.model_id)
        for allocation in strategy_plan.allocations:
            st=allocation.strategy
            if st not in _PARAMETER|_ORCHESTRATION: raise EvolutionaryMergePipelineError("unknown merge strategy")
            kind="PARAMETER_MERGE" if st in _PARAMETER else "ORCHESTRATION_ONLY"
            if allocation.strategy_class!=kind: raise EvolutionaryMergePipelineError("strategy routing class mismatch")
            share=allocation.evaluation_share
            if not math.isfinite(share) or not 0<share<=1: raise EvolutionaryMergePipelineError("allocation share invalid")
            if kind=="ORCHESTRATION_ONLY": continue
            for i,left in enumerate(ordered):
                for right in ordered[i+1:]:
                    cid=f"{st}:{left.model_id}+{right.model_id}"
                    payload={"id":cid,"strategy":st,"parents":[left.model_id,right.model_id],
                        "artifacts":[left.artifact_digest,right.artifact_digest],"share":share,"source":strategy_plan.digest}
                    rows.append(MergeCombination(cid,st,kind,(left.model_id,right.model_id),
                        (left.artifact_digest,right.artifact_digest),share,_hash(payload)))
        rows=sorted(rows,key=lambda x:(-x.allocation_share,x.strategy,x.candidate_id))[:max_combinations]
        if not rows: raise EvolutionaryMergePipelineError("no parameter merge candidates")
        payload={"source":strategy_plan.digest,"generation":strategy_plan.source_generation,
            "suite":strategy_plan.evaluation_suite_digest,"rows":[x.digest for x in rows]}
        return CombinationPlan(strategy_plan.digest,strategy_plan.source_generation,strategy_plan.evaluation_suite_digest,tuple(rows),_hash(payload))

@dataclass(frozen=True)
class CompatibilityAssessment:
    candidate_id:str; compatible:bool; reasons:tuple[str,...]; digest:str
    parameter_merge_permitted_for_evaluation:bool; proposal_only:bool=True

class Stage172CompatibilityGate:
    """Requires exact architecture, tokenizer, tensor schema, format, quantization, provenance and license."""
    def assess(self,plan:CombinationPlan,artifacts:Sequence[ModelArtifact],*,hold_active=False):
        if hold_active: raise EvolutionaryMergePipelineError("HOLD blocks Stage 172")
        if not plan.proposal_only or plan.model_merge_authorized or plan.weight_mutation_authorized: raise EvolutionaryMergePipelineError("unsafe Stage 171 plan")
        index={x.model_id:x for x in artifacts}; out=[]
        for c in plan.combinations:
            parents=[index.get(x) for x in c.parent_model_ids]; reasons=[]
            if any(x is None for x in parents): reasons.append("parent metadata missing")
            else:
                if tuple(x.artifact_digest for x in parents) != c.parent_artifact_digests:
                    reasons.append("parent artifact digest lineage mismatch")
                for field in ("architecture","tokenizer_digest","tensor_schema_digest","model_format","quantization","provenance_digest","license_id"):
                    values=[getattr(x,field) for x in parents]
                    if any(not x for x in values) or len(set(values))!=1: reasons.append(f"{field} mismatch or missing")
            ok=not reasons; payload={"candidate":c.candidate_id,"parents":c.parent_artifact_digests,"ok":ok,"reasons":reasons}
            out.append(CompatibilityAssessment(c.candidate_id,ok,tuple(reasons),_hash(payload),ok))
        return tuple(out)

@dataclass(frozen=True)
class MergeTrialEvidence:
    candidate_id:str; candidate_artifact_digest:str; evaluation_suite_digest:str
    trial_id:str; evaluator_id:str; replicate:int; quality:float; safety:float
    latency_ms:float; memory_mb:float; regression_count:int; signature:str; evidence_digest:str

@dataclass(frozen=True)
class CandidateEvaluation:
    candidate_id:str; strategy:str; trial_count:int; evaluator_ids:tuple[str,...]
    quality_median:float; safety_median:float; latency_median_ms:float; memory_median_mb:float
    regression_count:int; eligible:bool; evidence_digests:tuple[str,...]; digest:str

@dataclass(frozen=True)
class EvaluationReport:
    source_combination_plan_digest:str; evaluation_suite_digest:str
    evaluations:tuple[CandidateEvaluation,...]; digest:str; proposal_only:bool=True

class Stage173IndependentEvaluator:
    """Aggregates independently signed repeated evidence; it does not execute models."""
    def build(self,plan,compatibility,trials:Sequence[MergeTrialEvidence],*,verify_signature:Callable,
              hold_active=False,minimum_repeats=2,max_latency_ms=120000,max_memory_mb=65536):
        if hold_active: raise EvolutionaryMergePipelineError("HOLD blocks Stage 173")
        if not callable(verify_signature) or not 2<=minimum_repeats<=10: raise EvolutionaryMergePipelineError("independent verifier and repeat bound required")
        allowed={x.candidate_id for x in compatibility if x.compatible and x.parameter_merge_permitted_for_evaluation}
        seen=set(); groups={}
        for t in trials:
            if t.candidate_id not in allowed: raise EvolutionaryMergePipelineError("candidate not compatibility-cleared")
            for value,label in ((t.candidate_artifact_digest,"artifact"),(t.evaluation_suite_digest,"suite"),(t.evidence_digest,"evidence")): _digest(value,label)
            if t.evaluation_suite_digest!=plan.evaluation_suite_digest: raise EvolutionaryMergePipelineError("evaluation suite drift")
            if not _ID.fullmatch(t.trial_id or "") or not _ID.fullmatch(t.evaluator_id or "") or t.replicate<1 or not t.signature or len(t.signature)>8192: raise EvolutionaryMergePipelineError("trial identity or signature invalid")
            if t.trial_id in seen or t.evidence_digest in seen: raise EvolutionaryMergePipelineError("duplicate or replayed trial evidence")
            vals=(t.quality,t.safety,t.latency_ms,t.memory_mb)
            if not all(math.isfinite(x) for x in vals) or not 0<=t.quality<=1 or not 0<=t.safety<=1 or t.latency_ms<0 or t.memory_mb<0 or not isinstance(t.regression_count,int) or t.regression_count<0: raise EvolutionaryMergePipelineError("trial metrics invalid")
            if not verify_signature(t): raise EvolutionaryMergePipelineError("independent signature verification failed")
            seen.add(t.trial_id); seen.add(t.evidence_digest); groups.setdefault(t.candidate_id,[]).append(t)
        byid={x.candidate_id:x for x in plan.combinations}; results=[]
        for cid,items in sorted(groups.items()):
            if len(items)<minimum_repeats: continue
            if len({x.evaluator_id for x in items})!=len(items): raise EvolutionaryMergePipelineError("each repeat requires a distinct evaluator")
            if len({(x.candidate_artifact_digest,x.evaluation_suite_digest) for x in items})!=1: raise EvolutionaryMergePipelineError("replicates not comparable")
            if len({x.replicate for x in items})!=len(items): raise EvolutionaryMergePipelineError("duplicate replicate number")
            def med(k):
                v=sorted(getattr(x,k) for x in items); n=len(v)
                return v[n//2] if n%2 else (v[n//2-1]+v[n//2])/2
            q,s,l,m=med("quality"),med("safety"),med("latency_ms"),med("memory_mb"); reg=max(x.regression_count for x in items)
            eligible=q>=.70 and s>=.95 and reg==0 and l<=max_latency_ms and m<=max_memory_mb
            ev=tuple(sorted(x.evidence_digest for x in items)); payload={"candidate":cid,"strategy":byid[cid].strategy,"evidence":ev,"metrics":[q,s,l,m,reg],"eligible":eligible}
            results.append(CandidateEvaluation(cid,byid[cid].strategy,len(items),tuple(sorted(x.evaluator_id for x in items)),q,s,l,m,reg,eligible,ev,_hash(payload)))
        payload={"plan":plan.digest,"suite":plan.evaluation_suite_digest,"results":[x.digest for x in results]}
        return EvaluationReport(plan.digest,plan.evaluation_suite_digest,tuple(results),_hash(payload))

@dataclass(frozen=True)
class EvolutionarySelection:
    ranked_candidate_ids:tuple[str,...]; selected_for_next_trial:tuple[str,...]
    rejected_candidate_ids:tuple[str,...]; source_evaluation_digest:str; digest:str
    proposal_only:bool=True; selection_authorized:bool=False

class Stage174ParetoSelector:
    """Ranks eligible candidates on quality, safety, latency and memory while preserving a shortlist."""
    def build(self,report:EvaluationReport,*,max_selected=4,hold_active=False):
        if hold_active: raise EvolutionaryMergePipelineError("HOLD blocks Stage 174")
        if not report.proposal_only or not isinstance(max_selected,int) or not 1<=max_selected<=16: raise EvolutionaryMergePipelineError("invalid report or shortlist bound")
        eligible=[x for x in report.evaluations if x.eligible]; rejected=tuple(sorted(x.candidate_id for x in report.evaluations if not x.eligible))
        frontier=[]
        for x in eligible:
            dominated=False
            for y in eligible:
                if x==y: continue
                nw=y.quality_median>=x.quality_median and y.safety_median>=x.safety_median and y.latency_median_ms<=x.latency_median_ms and y.memory_median_mb<=x.memory_median_mb
                strict=y.quality_median>x.quality_median or y.safety_median>x.safety_median or y.latency_median_ms<x.latency_median_ms or y.memory_median_mb<x.memory_median_mb
                if nw and strict: dominated=True; break
            if not dominated: frontier.append(x)
        frontier.sort(key=lambda x:(-x.quality_median,-x.safety_median,x.latency_median_ms,x.memory_median_mb,x.candidate_id))
        rest=sorted([x for x in eligible if x not in frontier],key=lambda x:(-x.quality_median,-x.safety_median,x.latency_median_ms,x.candidate_id))
        ranked=tuple(x.candidate_id for x in frontier+rest); selected=ranked[:max_selected]
        payload={"source":report.digest,"ranked":ranked,"selected":selected,"rejected":rejected}
        return EvolutionarySelection(ranked,selected,rejected,report.digest,_hash(payload))

@dataclass(frozen=True)
class NextGenerationProposal:
    source_generation:int; proposed_generation:int; selected_candidate_ids:tuple[str,...]
    selection_digest:str; evaluation_suite_digest:str; digest:str
    proposal_only:bool=True; generation_advance_authorized:bool=False
    model_merge_authorized:bool=False; weight_mutation_authorized:bool=False
    model_activation_authorized:bool=False; production_switch_authorized:bool=False

class Stage175GenerationProposer:
    """Creates a next-generation proposal; it never advances or activates a generation."""
    def build(self,plan,report,selection,*,hold_active=False,kill_switch_active=False):
        if hold_active or kill_switch_active: raise EvolutionaryMergePipelineError("HOLD or kill switch blocks Stage 175")
        if plan.digest!=report.source_combination_plan_digest or plan.evaluation_suite_digest!=report.evaluation_suite_digest or selection.source_evaluation_digest!=report.digest or not selection.proposal_only or selection.selection_authorized:
            raise EvolutionaryMergePipelineError("Stage 171-174 lineage or authority mismatch")
        eligible={x.candidate_id for x in report.evaluations if x.eligible}
        if not selection.selected_for_next_trial or any(x not in eligible for x in selection.selected_for_next_trial): raise EvolutionaryMergePipelineError("only eligible candidates may be proposed")
        payload={"source":plan.source_generation,"target":plan.source_generation+1,"selected":selection.selected_for_next_trial,"selection":selection.digest,"suite":plan.evaluation_suite_digest}
        return NextGenerationProposal(plan.source_generation,plan.source_generation+1,selection.selected_for_next_trial,selection.digest,plan.evaluation_suite_digest,_hash(payload))

__all__=["EvolutionaryMergePipelineError","ModelArtifact","MergeCombination","CombinationPlan","Stage171CombinationPlanner","CompatibilityAssessment","Stage172CompatibilityGate","MergeTrialEvidence","CandidateEvaluation","EvaluationReport","Stage173IndependentEvaluator","EvolutionarySelection","Stage174ParetoSelector","NextGenerationProposal","Stage175GenerationProposer"]
