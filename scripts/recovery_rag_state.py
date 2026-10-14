"""Bounded import/export for sanitized Recovery RAG history."""
from __future__ import annotations
import argparse, json, re, sqlite3
from pathlib import Path
from scripts.recovery_rag import record_outcome

STATUSES = {"PASS", "NO_CHANGE", "FAIL", "TIMEOUT", "STOPPED", "BLOCKED"}
CATEGORIES = {"network_transient", "service_unavailable", "rate_limited", "test_regression", "timeout", "process_crash", "invalid_task", "invalid_evidence", "security_violation", "state_persistence_failure", "unknown"}
MAX_RECORDS = 200

def clean(v):
    if not isinstance(v, dict): raise ValueError("invalid RAG record")
    r = {k: v.get(k) for k in ("task_id", "status", "category", "fingerprint")}
    if not isinstance(r["task_id"], str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", r["task_id"]): raise ValueError("invalid task_id")
    if r["status"] not in STATUSES or r["category"] not in CATEGORIES: raise ValueError("status/category not allowlisted")
    if not isinstance(r["fingerprint"], str) or not re.fullmatch(r"[0-9a-f]{64}", r["fingerprint"]): raise ValueError("invalid fingerprint")
    return r

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("import", "export"), required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--namespace", default="distributed-loop")
    a = p.parse_args()
    if a.mode == "import":
        state = json.loads(a.state.read_text(encoding="utf-8"))
        records = state.get("recovery_rag", []) if isinstance(state, dict) else None
        if not isinstance(records, list) or len(records) > MAX_RECORDS: raise ValueError("invalid durable RAG history")
        seen = set()
        for item in records:
            r = clean(item); key = (r["task_id"], r["fingerprint"])
            if key not in seen: record_outcome(a.db, namespace=a.namespace, **r); seen.add(key)
        count = len(seen)
    else:
        with sqlite3.connect(str(a.db), timeout=5) as c:
            rows = c.execute("SELECT metadata_json FROM rag_documents WHERE namespace=? AND source='recovery_ai' ORDER BY updated_at DESC, id DESC LIMIT ?", (a.namespace, MAX_RECORDS)).fetchall()
        records=[]; seen=set()
        for (raw,) in rows:
            r=clean(json.loads(raw)); key=(r["task_id"],r["fingerprint"])
            if key not in seen: records.append(r); seen.add(key)
        a.state.write_text(json.dumps({"schema_version":1,"records":records},sort_keys=True)+"\n",encoding="utf-8")
        count=len(records)
    print(f"Recovery RAG {a.mode}: {count} sanitized records")

if __name__ == "__main__": main()
