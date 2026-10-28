"""Build a bounded, review-only candidate pool from trusted structured inputs.

This utility never creates tasks, issues, queue entries, or execution permissions.
Only allowlisted metadata is persisted; free-form content is length-bounded and
rendered as inert text in the summary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

MAX_CANDIDATES = 50
MAX_TITLE = 180
MAX_RATIONALE = 500
_ALLOWED_SOURCES = {"self_improvement", "idea_ai"}
_ALLOWED_STATUSES = {"proposed", "reviewed"}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")


def _clean_text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    value = "".join(ch for ch in value if ch in "\n\t" or ord(ch) >= 32)
    return " ".join(value.split())[:limit]


def normalize_candidate(row: object) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    source = row.get("source")
    title = _clean_text(row.get("title"), MAX_TITLE)
    rationale = _clean_text(row.get("rationale"), MAX_RATIONALE)
    source_id = row.get("source_id", "")
    status = row.get("status", "proposed")
    if source not in _ALLOWED_SOURCES or not title:
        return None
    if status not in _ALLOWED_STATUSES:
        return None
    if not isinstance(source_id, str) or (source_id and not _ID.fullmatch(source_id)):
        return None
    key_material = json.dumps(
        {"source": source, "title": title.casefold(), "rationale": rationale.casefold()},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    candidate_key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:24]
    return {
        "schema_version": 1, "candidate_key": candidate_key, "source": source,
        "source_id": source_id, "title": title, "rationale": rationale,
        "status": status, "execution_authorized": False,
    }


def build_pool(input_path: Path, store_path: Path, summary_path: Path) -> dict[str, int]:
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("candidate input is unavailable or invalid") from exc
    if not isinstance(payload, list):
        raise ValueError("candidate input must be a JSON list")

    existing: dict[str, dict[str, Any]] = {}
    if store_path.exists():
        try:
            old_rows = [json.loads(line) for line in store_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("candidate store is invalid; refusing to overwrite") from exc
        if not all(isinstance(row, dict) and row.get("schema_version") == 1
                   and isinstance(row.get("candidate_key"), str)
                   and row.get("execution_authorized") is False for row in old_rows):
            raise ValueError("candidate store schema is invalid; refusing to overwrite")
        existing = {row["candidate_key"]: row for row in old_rows}

    accepted = 0
    rejected = 0
    for raw in payload[:MAX_CANDIDATES * 4]:
        candidate = normalize_candidate(raw)
        if candidate is None:
            rejected += 1
            continue
        key = candidate["candidate_key"]
        if key not in existing:
            accepted += 1
        existing[key] = candidate
    rows = sorted(existing.values(), key=lambda row: (row["source"], row["candidate_key"]))[-MAX_CANDIDATES:]

    store_path.parent.mkdir(parents=True, exist_ok=True)
    temp = store_path.with_name(store_path.name + ".tmp")
    try:
        temp.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
        temp.replace(store_path)
    finally:
        if temp.exists():
            temp.unlink()

    lines = [
        "# Review-only improvement candidates", "",
        f"- Stored candidates: {len(rows)}", f"- Newly added: {accepted}",
        f"- Rejected input rows: {rejected}", "- Execution authorization: **none**",
        "- Queue / issue / PR creation: **not performed**", "",
    ]
    for row in rows:
        lines.extend([
            f"## {row['title']}", f"- Source: {row['source']}",
            f"- Candidate key: `{row['candidate_key']}`", f"- Status: {row['status']}",
            f"- Rationale: {row['rationale'] or '(not provided)'}", "",
        ])
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    return {"stored": len(rows), "added": accepted, "rejected": rejected}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build_pool(args.input, args.store, args.summary)
    except (OSError, ValueError) as exc:
        print(f"review candidate bridge stopped safely: {exc}")
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
