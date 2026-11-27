"""Rule-based, read-only investigator for Distributed Loop monitor reports.

Produces bounded, actionable diagnostics. It never changes queue, approval, HOLD,
workflow, repository, or deployment state.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
from typing import Any

MAX_FINDINGS = 20

def investigate(report: Any) -> dict:
    findings=[]
    if not isinstance(report, dict):
        return {"schema_version":1,"status":"BLOCKED","findings":[{"severity":"critical","code":"REPORT_INVALID","cause":"Monitor report is missing or malformed","evidence":{},"recommendation":"Restore monitor evidence collection; do not resume the Loop."}]}
    checks=report.get("checks") if isinstance(report.get("checks"),dict) else {}
    def add(severity,code,cause,evidence,recommendation):
        if len(findings)<MAX_FINDINGS:
            findings.append({"severity":severity,"code":code,"cause":cause,"evidence":evidence,"recommendation":recommendation})
    if report.get("status") in {"BLOCKED","FAIL"}:
        add("critical","MONITOR_BLOCKED","Monitor did not establish a healthy state",{"status":report.get("status"),"failure_reason":report.get("failure_reason")},"Inspect the failed checks and missing evidence; keep execution approval denied.")
    for name,check in checks.items():
        if not isinstance(check,dict): continue
        status=check.get("status")
        if status in {"BLOCKED","FAIL"}:
            detail=str(check.get("detail") or check.get("outcome") or "No detail provided")[:500]
            code="CHECK_"+str(name).upper()
            add("high",code,"Check '"+str(name)+"' failed or could not be verified",{"status":status,"detail":detail},"Repair only the named evidence or validation path; rerun its targeted tests before broader operation.")
        elif status=="HOLD":
            add("warning","SAFETY_HOLD_"+str(name).upper(),"A safety hold or review gate remains active",{"status":status,"detail":str(check.get("detail",""))[:300]},"Do not clear the hold automatically. Request the required human review.")
    coverage=checks.get("schedule_slot_coverage",{})
    if isinstance(coverage,dict):
        missing=coverage.get("missing_slots",[])
        if missing:
            categories={}
            for item in missing[:MAX_FINDINGS]:
                if isinstance(item,dict):
                    code=str(item.get("status","UNKNOWN"))
                    categories[code]=categories.get(code,0)+1
            add("high","SCHEDULER_SLOT_GAPS","Scheduled slots are missing or unverified",{"count":len(missing),"types":categories,"examples":missing[:5]},"Check workflow registration, schedule event records, and decision artifacts. Do not manually dispatch to mask a gap.")
    queue=checks.get("queue_and_approval",{})
    if isinstance(queue,dict):
        for key in ("eligible_catalog_count","queued_task_count","held_task_count","review_required_count","model_unavailable_count","exhaustion_reason"):
            if key in queue: pass
        detail=queue.get("detail") or queue.get("outcome")
        if queue.get("status") in {"BLOCKED","HOLD"} or "exhaust" in str(detail).lower():
            add("high","QUEUE_OR_APPROVAL_BLOCK","Queue/approval gate is blocked or exhausted",{"status":queue.get("status"),"detail":str(detail)[:500]},"Inspect eligible catalog tasks and provider availability. Preserve approval, held, review, and task allowlists.")
    if not findings:
        add("info","NO_ACTIONABLE_FINDINGS","No actionable issue detected from the supplied monitor report",{"monitor_status":report.get("status")},"Continue read-only monitoring; this report is not a task PASS or an execution authorization.")
    overall="BLOCKED" if any(f["severity"]=="critical" for f in findings) else ("HOLD" if any(f["severity"]=="warning" for f in findings) else "INVESTIGATED")
    return {"schema_version":1,"status":overall,"source_monitor_run_id":report.get("run_id"),"source_head_sha":report.get("monitor_head_sha"),"finding_count":len(findings),"findings":findings,"dispatch_allowed":False,"state_mutation_allowed":False,"execution_approval":"DENY"}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    try: report=json.loads(Path(args.input).read_text(encoding="utf-8"))
    except (OSError,ValueError): report=None
    result=investigate(report)
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\\n",encoding="utf-8")
    print(json.dumps({"status":result["status"],"finding_count":result["finding_count"],"output":str(out)}))
    return 0 if result["status"] in {"INVESTIGATED"} else 1
if __name__=="__main__": raise SystemExit(main())
