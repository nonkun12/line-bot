"""Deterministic repair candidate comparison; metadata only, no patch application."""
from __future__ import annotations
import hashlib,json,math
from typing import Any,Mapping,Sequence

def _seal(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def _valid_num(x):return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)

def validate_candidate(c:Mapping[str,Any],allowed_risk:Sequence[str])->list[str]:
 errors=[]
 for k in ("candidate_id","change_summary","evidence_ref","test_plan_ref","rollback_ref"):
  if not isinstance(c.get(k),str) or not c[k].strip():errors.append("candidate_missing:"+k)
 if c.get("risk_class") not in allowed_risk:errors.append("candidate_risk_disallowed")
 if not _valid_num(c.get("estimated_cost")) or c["estimated_cost"]<0:errors.append("candidate_cost_invalid")
 if not _valid_num(c.get("expected_impact")) or not -1<=c["expected_impact"]<=1:errors.append("candidate_impact_invalid")
 if c.get("scope_files") is not None and (not isinstance(c["scope_files"],list) or not c["scope_files"]):errors.append("candidate_scope_invalid")
 return errors

def rank_candidates(candidates:Sequence[Mapping[str,Any]],*,allowed_risk:Sequence[str],max_candidates:int=10)->dict:
 errors=[];ids=set();validated=[]
 if not isinstance(max_candidates,int) or isinstance(max_candidates,bool) or max_candidates<1:errors.append("max_candidates_invalid");max_candidates=1
 if len(candidates)>max_candidates:errors.append("candidate_count_exceeds_limit")
 for i,c in enumerate(candidates):
  cid=c.get("candidate_id")
  if not isinstance(cid,str) or not cid.strip() or cid in ids:errors.append(f"candidate_id_duplicate_or_invalid:{i}")
  else:ids.add(cid)
  ce=validate_candidate(c,allowed_risk)
  errors.extend(f"{i}:{e}" for e in ce)
  if not ce:validated.append(c)
 # Deterministic sort by declared impact desc, cost asc, id. No weights/real-world claims.
 ranked=sorted(validated,key=lambda c:(-c["expected_impact"],c["estimated_cost"],c["candidate_id"]))
 result={"ranked_ids":[c["candidate_id"] for c in ranked],"candidate_count":len(candidates),"valid_count":len(validated),"errors":errors,"pass":not errors,"ranking_method":"declared impact desc, declared cost asc, candidate id"}
 return {"stage":501,"result":result,"seal":_seal(result),"execution_authorized":False,"benefit_verified":False}

def check_repair_conflicts(conflicts:Sequence[Mapping[str,Any]])->dict:
 errors=[]
 if not conflicts:errors.append("conflict_records_empty")
 for i,c in enumerate(conflicts):
  for k in ("candidate_a","candidate_b","conflict_type","evidence_ref"):
   if not isinstance(c.get(k),str) or not c[k].strip():errors.append(f"conflict_field_missing:{i}:{k}")
  if c.get("resolved") is True and not isinstance(c.get("resolution_ref"),str):errors.append(f"conflict_resolution_ref_missing:{i}")
 return {"stage":502,"pass":not errors,"errors":errors}

def check_candidate_dependency_graph(nodes:Sequence[str],edges:Sequence[Mapping[str,Any]])->dict:
 errors=[];node_set=set(nodes)
 if len(node_set)!=len(nodes):errors.append("dependency_node_duplicate")
 if any(not isinstance(n,str) or not n.strip() for n in nodes):errors.append("dependency_node_invalid")
 adj={n:[] for n in nodes}
 for i,e in enumerate(edges):
  a,b=e.get("from"),e.get("to")
  if a not in node_set or b not in node_set:errors.append(f"dependency_edge_unknown_node:{i}")
  elif a==b:errors.append(f"dependency_self_loop:{i}")
  else:adj[a].append(b)
 visiting=set();visited=set()
 def dfs(n):
  if n in visiting:return True
  if n in visited:return False
  visiting.add(n)
  for m in adj.get(n,[]):
   if dfs(m):return True
  visiting.remove(n);visited.add(n);return False
 if any(dfs(n) for n in nodes):errors.append("dependency_cycle_detected")
 return {"stage":503,"pass":not errors,"errors":errors}

def check_repair_risk_matrix(entries:Sequence[Mapping[str,Any]],risk_levels:Sequence[str])->dict:
 errors=[]
 if not entries:errors.append("risk_matrix_empty")
 for i,e in enumerate(entries):
  for k in ("candidate_id","risk_class","mitigation_ref","rollback_ref"):
   if not isinstance(e.get(k),str) or not e[k].strip():errors.append(f"risk_matrix_missing:{i}:{k}")
  if e.get("risk_class") not in risk_levels:errors.append(f"risk_level_unknown:{i}")
  if e.get("mitigated") is not True:errors.append(f"risk_not_mitigated:{i}")
 return {"stage":504,"pass":not errors,"errors":errors}

def evaluate_501_505(*,candidates,allowed_risk,max_candidates,conflicts,nodes,edges,risk_matrix,risk_levels,unresolved_holds):
 checks=[rank_candidates(candidates,allowed_risk=allowed_risk,max_candidates=max_candidates)["result"],check_repair_conflicts(conflicts),check_candidate_dependency_graph(nodes,edges),check_repair_risk_matrix(risk_matrix,risk_levels)]
 hold_err=["unresolved_holds_present"] if unresolved_holds else []
 checks.append({"stage":505,"pass":not hold_err,"errors":hold_err})
 good=all(x.get("pass",False) for x in checks);record={"checks":checks,"pass":good}
 return {"stage":505,"status":"READY_FOR_REVIEW" if good else "HOLD","checks":checks,"seal":_seal(record),"proposal_only":True,"patch_applied":False,"execution_authorized":False,"hold_release_authorized":False,"merge_authorized":False,"deployment_authorized":False}
