"""Persist REA observations separately from development failure history.

REA gate outcomes are security/evidence observations, not developer task failures.
This store keeps only bounded categorical metadata and never grants authority.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from scripts.rea_control_tower_adapter import rea_evidence_is_valid_pass

MAX_RECORDS = 200
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_REASON_CATEGORIES = {
    "rea_high_or_critical_finding": "finding_block",
    "rea_scan_incomplete": "evidence_block",
    "rea_sha_mismatch": "evidence_block",
    "rea_adapter_error": "evidence_block",
    "rea_report_invalid": "evidence_block",
    "rea_findings_invalid": "evidence_block",
    "rea_finding_invalid": "evidence_block",
    "rea_finding_evidence_invalid": "evidence_block",
    "rea_finding_schema_invalid": "evidence_block",
    "rea_scanner_status_invalid": "evidence_block",
    "rea_scanner_status_inconsistent": "evidence_block",
    "expected_sha_invalid": "evidence_block",
}


def _count(value: object) -> bool:
    return type(value) is int and 0 <= value <= 1_000_000


def validate_durable_rea_observations(records: object) -> list[dict[str, object]]:
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise ValueError("REA observation history must be a bounded list")
    validated: list[dict[str, object]] = []
    fields = {
        "record_type", "cycle_id", "task_id", "gate", "scanner_status",
        "category", "finding_count", "critical_count", "blocking_count",
        "target_sha",
    }
    for row in records:
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError("REA observation schema is invalid")
        if row.get("record_type") != "rea_observation":
            raise ValueError("REA observation record type is invalid")
        cycle_id, task_id = row.get("cycle_id"), row.get("task_id")
        if not isinstance(cycle_id, str) or not re.fullmatch(r"[0-9]{1,20}", cycle_id):
            raise ValueError("REA observation cycle ID is invalid")
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
            raise ValueError("REA observation task ID is invalid")
        if not all(_count(row.get(key)) for key in ("finding_count", "critical_count", "blocking_count")):
            raise ValueError("REA observation counts are invalid")
        if row["critical_count"] > row["blocking_count"] or row["blocking_count"] > row["finding_count"]:
            raise ValueError("REA observation severity counts are inconsistent")
        target_sha = row.get("target_sha")
        if target_sha is not None and (not isinstance(target_sha, str) or not _SHA.fullmatch(target_sha)):
            raise ValueError("REA observation target SHA is invalid")
        gate, scanner, category = row.get("gate"), row.get("scanner_status"), row.get("category")
        finding_count, critical, blocking = row["finding_count"], row["critical_count"], row["blocking_count"]
        if gate == "PASS":
            if (
                scanner not in {"PASS", "FINDINGS"}
                or category not in {"clean_scan", "nonblocking_findings"}
                or (category == "clean_scan" and (scanner != "PASS" or finding_count != 0))
                or (category == "nonblocking_findings" and (scanner != "FINDINGS" or finding_count < 1))
                or critical != 0 or blocking != 0 or target_sha is None
            ):
                raise ValueError("REA PASS observation is inconsistent")
        elif gate == "BLOCKED":
            if category not in {"finding_block", "evidence_block"}:
                raise ValueError("REA BLOCKED category is invalid")
            if category == "finding_block" and (
                scanner != "FINDINGS" or blocking < 1 or finding_count < blocking or target_sha is None
            ):
                raise ValueError("REA finding block is inconsistent")
            if category == "evidence_block" and (
                scanner != "BLOCKED" or finding_count != 0 or critical != 0
                or blocking != 0 or target_sha is not None
            ):
                raise ValueError("REA evidence block is inconsistent")
        else:
            raise ValueError("REA observation gate is invalid")
        validated.append(dict(row))
    return validated[-MAX_RECORDS:]


def _read(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError("REA history is corrupt; refusing to overwrite") from exc
        rows.append(row)
    return validate_durable_rea_observations(rows[-MAX_RECORDS:])


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    rows = validate_durable_rea_observations(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def append_rea_observations(
    history_path: Path, results_path: Path, catalog_path: Path, *, cycle_id: str
) -> int:
    if not isinstance(cycle_id, str) or not re.fullmatch(r"[0-9]{1,20}", cycle_id):
        raise ValueError("REA cycle ID is invalid")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    tasks = catalog.get("tasks") if isinstance(catalog, dict) else None
    if not isinstance(tasks, list):
        raise ValueError("task catalog is invalid")
    registered = {
        row.get("id") for row in tasks
        if isinstance(row, dict) and isinstance(row.get("id"), str) and _TASK_ID.fullmatch(row["id"])
    }
    rows = []
    for line in results_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        result = json.loads(line)
        if not isinstance(result, dict):
            raise ValueError("loop result row is invalid")
        task_id, rea = result.get("task_id"), result.get("rea")
        if not isinstance(task_id, str) or task_id not in registered or not isinstance(rea, dict):
            continue
        gate = rea.get("gate")
        if gate == "PASS":
            base_sha = result.get("base_sha")
            if not isinstance(base_sha, str) or not rea_evidence_is_valid_pass(rea, expected_sha=base_sha):
                raise ValueError("REA PASS evidence failed independent validation")
            category = "nonblocking_findings" if rea["finding_count"] else "clean_scan"
        elif gate == "BLOCKED":
            reason = rea.get("reason_code")
            category = _REASON_CATEGORIES.get(reason)
            if (
                category is None
                or rea.get("execution_authorized") is not False
                or rea.get("patch_authorized") is not False
                or rea.get("hold_clear_authorized") is not False
                or rea.get("merge_deploy_authorized") is not False
                or rea.get("scanner_status") not in {"BLOCKED", "FINDINGS"}
                or not all(_count(rea.get(key)) for key in ("finding_count", "critical_count", "blocking_count"))
                or not isinstance(rea.get("findings"), list)
                or len(rea["findings"]) > 100
            ):
                raise ValueError("REA BLOCKED evidence failed independent validation")
            if category == "finding_block":
                base_sha = result.get("base_sha")
                if (
                    rea.get("target_sha") != base_sha or not isinstance(base_sha, str)
                    or not _SHA.fullmatch(base_sha) or rea.get("blocking_count", 0) < 1
                ):
                    raise ValueError("REA finding block is not bound to the task base")
            elif rea.get("scanner_status") != "BLOCKED":
                raise ValueError("REA evidence block scanner status is inconsistent")
        else:
            continue
        target_sha = rea.get("target_sha")
        rows.append({
            "record_type": "rea_observation",
            "cycle_id": cycle_id,
            "task_id": task_id,
            "gate": gate,
            "scanner_status": rea["scanner_status"],
            "category": category,
            "finding_count": rea["finding_count"],
            "critical_count": rea["critical_count"],
            "blocking_count": rea["blocking_count"],
            "target_sha": target_sha if isinstance(target_sha, str) and _SHA.fullmatch(target_sha) else None,
        })
    existing = _read(history_path)
    identities = {(row["cycle_id"], row["task_id"]) for row in existing}
    additions = [row for row in rows if (row["cycle_id"], row["task_id"]) not in identities]
    _write(history_path, existing + additions)
    return len(additions)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("import", "export", "append"))
    parser.add_argument("--state", type=Path)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--results", type=Path)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--cycle-id", default="")
    args = parser.parse_args(argv)
    if args.mode == "append":
        if args.results is None or args.catalog is None:
            raise SystemExit("--results and --catalog are required for append")
        count = append_rea_observations(args.history, args.results, args.catalog, cycle_id=args.cycle_id)
        print(f"REA_SELF_IMPROVEMENT_OBSERVATIONS_APPENDED={count}")
        return 0
    if args.state is None:
        raise SystemExit("--state is required for import/export")
    state = json.loads(args.state.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise SystemExit("durable state must be an object")
    if args.mode == "import":
        rows = validate_durable_rea_observations(state.get("rea_observations", []))
        _write(args.history, rows)
        print(f"REA_SELF_IMPROVEMENT_HISTORY_IMPORTED={len(rows)}")
        return 0
    rows = validate_durable_rea_observations(_read(args.history))
    state["rea_observations"] = rows
    temp = args.state.with_name(args.state.name + ".tmp")
    try:
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(args.state)
    finally:
        if temp.exists():
            temp.unlink()
    print(f"REA_SELF_IMPROVEMENT_HISTORY_EXPORTED={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
