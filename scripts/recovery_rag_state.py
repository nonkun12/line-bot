"""Bounded import/export for sanitized Recovery RAG history."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

from scripts.recovery_rag import record_outcome

STATUSES = {"PASS", "NO_CHANGE", "FAIL", "TIMEOUT", "STOPPED", "BLOCKED"}
CATEGORIES = {
    "network_transient", "service_unavailable", "rate_limited",
    "test_regression", "timeout", "process_crash", "invalid_task",
    "invalid_evidence", "security_violation", "state_persistence_failure",
    "unknown",
}
MAX_RECORDS = 200


def clean(value):
    if not isinstance(value, dict):
        raise ValueError("invalid RAG record")
    record = {key: value.get(key) for key in ("task_id", "status", "category", "fingerprint")}
    if not isinstance(record["task_id"], str) or not re.fullmatch(
        r"[A-Za-z0-9._-]{1,100}", record["task_id"]
    ):
        raise ValueError("invalid task_id")
    if record["status"] not in STATUSES or record["category"] not in CATEGORIES:
        raise ValueError("status/category not allowlisted")
    if not isinstance(record["fingerprint"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", record["fingerprint"]
    ):
        raise ValueError("invalid fingerprint")
    return record


def import_state(state_path, db_path, namespace):
    state = json.loads(state_path.read_text(encoding="utf-8"))
    records = state.get("recovery_rag", []) if isinstance(state, dict) else None
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise ValueError("invalid durable RAG history")
    seen = set()
    for item in records:
        record = clean(item)
        key = (record["task_id"], record["fingerprint"])
        if key not in seen:
            record_outcome(db_path, namespace=namespace, **record)
            seen.add(key)
    return len(seen)


def export_state(db_path, output_path, namespace):
    with sqlite3.connect(str(db_path), timeout=5) as connection:
        rows = connection.execute(
            "SELECT metadata_json FROM rag_documents "
            "WHERE namespace=? AND source='recovery_ai' "
            "ORDER BY updated_at DESC, id DESC LIMIT ?",
            (namespace, MAX_RECORDS),
        ).fetchall()
    records = []
    seen = set()
    for (raw,) in rows:
        record = clean(json.loads(raw))
        key = (record["task_id"], record["fingerprint"])
        if key not in seen:
            records.append(record)
            seen.add(key)
    output_path.write_text(
        json.dumps({"schema_version": 1, "records": records}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return len(records)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("import", "export"), required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--namespace", default="distributed-loop")
    args = parser.parse_args()
    if args.mode == "import":
        count = import_state(args.state, args.db, args.namespace)
    else:
        count = export_state(args.db, args.state, args.namespace)
    print(f"Recovery RAG {args.mode}: {count} sanitized records")


if __name__ == "__main__":
    main()
