"""Publish bounded review-only autonomous task candidate Issues."""
from __future__ import annotations
import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any
from scripts.autonomous_task_issue_drafts import MAX_DRAFTS, SPEC_MARKER, TASK_ID

LABEL = "autonomous-task-candidate"

def _run(args: list[str]) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout

def _issues(repo: str) -> list[dict[str, Any]]:
    raw = _run(["gh", "api", "--paginate", "--jq", '.[] | select(has("pull_request") | not)',
                f"repos/{repo}/issues?state=all&per_page=100"])
    return [json.loads(line) for line in raw.splitlines() if line.strip()]

def _ids(rows: list[dict[str, Any]]) -> set[str]:
    found = set()
    for row in rows:
        body = row.get("body")
        if not isinstance(body, str) or body.count(SPEC_MARKER) != 2:
            continue
        try:
            _, raw, _ = body.split(SPEC_MARKER)
            spec = json.loads(raw.strip())
        except (ValueError, TypeError):
            continue
        task_id = spec.get("id") if isinstance(spec, dict) else None
        if isinstance(task_id, str) and TASK_ID.fullmatch(task_id):
            found.add(task_id)
    return found

def _validate(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > MAX_DRAFTS:
        raise ValueError("draft batch exceeds the bounded limit")
    result, seen = [], set()
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("invalid draft")
        task_id, title, body = row.get("task_id"), row.get("title"), row.get("body")
        if (not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id) or task_id in seen
            or not isinstance(title, str) or not title or len(title) > 180
            or not isinstance(body, str) or body.count(SPEC_MARKER) != 2
            or "Queue admission: not authorized" not in body
            or "実行承認ではありません" not in body):
            raise ValueError("draft violates the review-only contract")
        _, raw, _ = body.split(SPEC_MARKER)
        spec = json.loads(raw.strip())
        if not isinstance(spec, dict) or spec.get("id") != task_id:
            raise ValueError("embedded candidate identity mismatch")
        if spec.get("execution_approved") is True or spec.get("execution_authorized") is True:
            raise ValueError("draft must never carry execution authority")
        if not isinstance(spec.get("allowed_paths"), list) or len(spec["allowed_paths"]) != 1:
            raise ValueError("draft allowed path must be singular")
        seen.add(task_id)
        result.append({"task_id": task_id, "title": title, "body": body})
    return result

def publish(drafts: list[dict[str, str]], repo: str) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("invalid repository")
    if not drafts:
        return {"status": "NO_DRAFTS", "created": [], "execution_approval_granted": False}
    _run(["gh", "api", f"repos/{repo}/labels/{LABEL}"])
    created, duplicates = [], 0
    for draft in drafts:
        if draft["task_id"] in _ids(_issues(repo)):
            duplicates += 1
            continue
        url = _run(["gh", "issue", "create", "--repo", repo, "--title", draft["title"],
                    "--body", draft["body"], "--label", LABEL]).strip()
        if not url.startswith("https://github.com/") or "/issues/" not in url:
            raise RuntimeError("GitHub did not return a canonical Issue URL")
        created.append(url)
    return {"status": "PUBLISHED" if created else "ALL_DUPLICATES", "created": created,
            "skipped_duplicates": duplicates, "execution_approval_granted": False}

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drafts", type=Path, required=True)
    parser.add_argument("--repo", required=True)
    args = parser.parse_args(argv)
    try:
        drafts = _validate(json.loads(args.drafts.read_text(encoding="utf-8")))
        result = publish(drafts, args.repo)
    except (OSError, json.JSONDecodeError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"AUTONOMOUS_TASK_ISSUE_PUBLISH_BLOCKED: {type(exc).__name__}")
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
