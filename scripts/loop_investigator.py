"""Read-only Loop Investigator for bounded monitor evidence."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Any

MAX_FINDINGS = 20

def investigate(report: Any) -> dict:
    findings = []
    if not isinstance(report, dict):
        findings.append({"severity":"critical","code":"REPORT_INVALID","cause":"Monitor report missing or malformed","evidence":{},"recommendation":"Restore monitor evidence collection; keep execution disabled."})
        return {"schema_version":1,"status":"BLOCKED","finding_count":1,"findings":findings,"dispatch_allowed":False,"state_mutation_allowed":False,"execution_approval":"DENY"}
    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    def add(severity, code, cause, evidence, recommendation):
        if len(findings) < MAX_FINDINGS:
            findings.append({"severity":severity,"code":code,"cause":cause,"evidence":evidence,"recommendation":recommendation})
    if report.get("status") in {"BLOCKED","FAIL"}:
        add("critical","MONITOR_BLOCKED","Monitor did not establish a healthy state",{"status":report.get("status"),"failure_reason":report.get("failure_reason")},"Inspect failed checks and missing evidence; do not dispatch or resume automatically.")
    for name, check in checks.items():
        if not isinstance(check, dict): continue
        status = check.get("status")
        detail = str(check.get("detail") or check.get("outcome") or "No details provided")[:500]
        if status in {"BLOCKED","FAIL"}:
            add("high","CHECK_"+str(name).upper(),"Check "+str(name)+" failed or is unverified",{"status":status,"detail":detail},"Repair only the identified path; run focused tests and verify evidence.")
        elif status == "HOLD":
            add("warning","SAFETY_HOLD_"+str(name).upper(),"Safety hold/review gate remains active",{"status":status,"detail":detail},"Keep the hold. Human review is required; investigator cannot clear it.")
    coverage = checks.get("schedule_slot_coverage", {})
    if isinstance(coverage, dict):
        missing = coverage.get("missing_slots", [])
        if isinstance(missing, list) and missing:
            types = {}
            for item in missing[:MAX_FINDINGS]:
                if isinstance(item, dict):
                    code = str(item.get("status", "UNKNOWN"))
                    types[code] = types.get(code, 0) + 1
            add("high","SCHEDULER_SLOT_GAPS","Scheduled slots are missing or unverified",{"count":len(missing),"types":types,"examples":missing[:5]},"Verify workflow registration, scheduled event evidence, and decision artifacts; do not use manual dispatch to mask gaps.")
    queue = checks.get("queue_and_approval", {})
    if isinstance(queue, dict):
        detail = str(queue.get("detail") or queue.get("outcome") or "")
        if queue.get("status") in {"BLOCKED","HOLD"} or "exhaust" in detail.lower():
            add("high","QUEUE_OR_APPROVAL_BLOCK","Queue/approval gate is blocked or exhausted",{"status":queue.get("status"),"detail":detail[:500]},"Inspect catalog eligibility and provider availability while preserving approvals, holds, reviews, and allowlists.")
    if not findings:
        add("info","NO_ACTIONABLE_FINDINGS","No actionable issue found in supplied evidence",{"monitor_status":report.get("status")},"Continue read-only monitoring; this is not a task PASS or execution authorization.")
    critical = any(f["severity"]=="critical" for f in findings)
    held = any(f["severity"]=="warning" for f in findings)
    status = "BLOCKED" if critical else ("HOLD" if held else "INVESTIGATED")
    return {"schema_version":1,"status":status,"source_monitor_run_id":report.get("run_id"),"source_head_sha":report.get("monitor_head_sha"),"finding_count":len(findings),"findings":findings,"dispatch_allowed":False,"state_mutation_allowed":False,"execution_approval":"DENY"}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    try:
        report=json.loads(Path(args.input).read_text(encoding="utf-8"))
    except (OSError,ValueError):
        report=None
    result=investigate(report)
    output=Path(args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":result["status"],"finding_count":result["finding_count"],"output":str(output)}))
    return 0 if result["status"]=="INVESTIGATED" else 1

if __name__=="__main__":
    raise SystemExit(main())
