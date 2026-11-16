"""Bounded, deterministic five-stage RSI test cycle for GitHub Actions.

Runs only a fixed set of repository-owned unittest files. It does not call an
LLM, access secrets, use a network client, modify source files, claim queue
tasks, or authorize patch/merge/deploy operations.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Any

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT_SECONDS = 90
SUITES = (
    ("rsi-state-machine", "test_orca_recursive_self_improvement.py"),
    ("queue-state-machine", "test_orca_github_task_queue.py"),
    ("execution-gate", "test_orca_github_execution_gate.py"),
    ("worker-boundary", "test_orca_github_worker_dry_run.py"),
    ("atomic-claim", "test_orca_github_atomic_claim.py"),
    ("atomic-finish", "test_orca_github_atomic_finish.py"),
)


def run_suite(suite_id: str, filename: str) -> dict[str, Any]:
    if filename not in {row[1] for row in SUITES}:
        raise ValueError("test_target_not_allowlisted")
    command = [sys.executable, "-m", "unittest", "discover",
               "-s", "tests", "-p", filename, "-v"]
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(ROOT),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "HOME": os.environ.get("HOME", "/tmp"),
        "CI": "true",
    }
    try:
        result = subprocess.run(command, cwd=ROOT, env=env,
                                capture_output=True, text=True,
                                timeout=TIMEOUT_SECONDS, check=False)
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        failures = len(re.findall(r"^(?:FAIL|ERROR):", output, re.MULTILINE))
        match = re.search(r"Ran (\d+) tests?", output)
        return {
            "suite_id": suite_id,
            "status": "PASS" if result.returncode == 0 else "FAIL",
            "exit_code": result.returncode,
            "tests_run": int(match.group(1)) if match else None,
            "failure_count": failures,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired:
        return {
            "suite_id": suite_id, "status": "TIMEOUT", "exit_code": None,
            "tests_run": None, "failure_count": None, "timed_out": True,
        }


def diagnose(results: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{
        "suite_id": row["suite_id"],
        "classification": "timeout" if row["timed_out"] else "test_failure",
        "scope": row["suite_id"],
    } for row in results if row["status"] != "PASS"]


def hypothesize(diagnoses: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{
        "suite_id": row["suite_id"],
        "hypothesis": (
            "test runtime exceeded the fixed timeout; inspect blocking operations"
            if row["classification"] == "timeout"
            else "a regression may exist in this safety contract; inspect the failing assertion"
        ),
        "confidence": "unverified",
    } for row in diagnoses]


def select(baseline: list[dict[str, Any]],
           experiments: list[dict[str, Any]]) -> str:
    if all(row["status"] == "PASS" for row in baseline):
        return "PASS"
    reruns = {row["suite_id"]: row for row in experiments}
    unresolved = [
        row for row in baseline
        if row["status"] != "PASS"
        and reruns.get(row["suite_id"], {}).get("status") != "PASS"
    ]
    return "BLOCKED" if unresolved else "FLAKY_REVIEW_REQUIRED"


def run_cycle(*, runner: Callable[[str, str], dict[str, Any]] = run_suite,
              created_at: str | None = None) -> dict[str, Any]:
    timestamp = created_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # 1 Evaluate: fixed baseline matrix.
    baseline = [runner(suite_id, filename) for suite_id, filename in SUITES]
    # 2 Diagnose: classify evidence without asserting root cause.
    findings = diagnose(baseline)
    # 3 Hypothesize: bounded, explicitly unverified investigation directions.
    hypotheses = hypothesize(findings)
    # 4 Experiment: one clean-process rerun for each failed non-timeout suite.
    filename_by_id = {suite_id: filename for suite_id, filename in SUITES}
    experiments = [
        runner(row["suite_id"], filename_by_id[row["suite_id"]])
        for row in baseline if row["status"] != "PASS" and not row["timed_out"]
    ]
    # 5 Select & Evolve: failures stop for human review.
    decision = select(baseline, experiments)
    return {
        "schema_version": 1,
        "cycle_type": "github_native_deterministic_rsi",
        "created_at": timestamp,
        "stages": {
            "evaluate": {"status": "COMPLETE", "baseline": baseline},
            "diagnose": {"status": "COMPLETE", "findings": findings},
            "hypothesize": {"status": "COMPLETE", "hypotheses": hypotheses},
            "experiment": {"status": "COMPLETE", "reruns": experiments},
            "select_evolve": {
                "status": decision,
                "next_action": "continue_next_scheduled_cycle" if decision == "PASS"
                               else "stop_and_require_human_review",
                "source_mutation": False, "auto_apply": False,
                "auto_merge": False, "auto_deploy": False,
            },
        },
        "execution_boundary": {
            "only_fixed_unittest_targets": True, "llm_used": False,
            "secrets_read": False, "network_access_requested": False,
            "repository_files_modified": False, "queue_claimed": False,
            "execution_authorized_for_code_changes": False,
        },
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/orca-rsi/cycle.json")
    args = parser.parse_args()
    report = run_cycle()
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    stage = report["stages"]
    baseline = stage["evaluate"]["baseline"]
    passed = sum(row["status"] == "PASS" for row in baseline)
    print(json.dumps({
        "decision": stage["select_evolve"]["status"],
        "baseline_passed": passed, "baseline_total": len(baseline),
        "artifact": args.output,
    }, ensure_ascii=False, sort_keys=True))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("# Orca RSI — five-stage deterministic cycle\n\n")
            handle.write(f"- Decision: **{stage['select_evolve']['status']}**\n")
            handle.write(f"- Baseline: {passed}/{len(baseline)} suites passed\n")
            handle.write(f"- Diagnoses: {len(stage['diagnose']['findings'])}\n")
            handle.write(f"- Experiment reruns: {len(stage['experiment']['reruns'])}\n")
            handle.write("- Source changes / queue claims / merge / deploy: none\n")
    return 0 if stage["select_evolve"]["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
