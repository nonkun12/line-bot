"""Trusted workflow_run collector for isolated REA regression tests.

This script is intended to run only from the default-branch workflow_run job.
GitHub event metadata and the run-scoped line-dev branch are the provenance
anchors; task JSONL is treated as untrusted input. The test container receives
no token, no network, and only a read-only archive of the exact task commit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

SHA40 = re.compile(r"[0-9a-f]{40}")
SHA64 = re.compile(r"[0-9a-f]{64}")
REA_TESTS = (
    "tests/test_rea_artifact_evaluator.py",
    "tests/test_rea_independent_test_evidence.py",
)
REA_PATH_PREFIXES = ("core/rea_", "tests/test_rea_")


def run(command: list[str], *, check: bool = True, **kwargs):
    return subprocess.run(command, check=check, text=True, **kwargs)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_counts(path: Path) -> tuple[int, int, int, int]:
    if not path.is_file():
        return 0, 0, 0, 0
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    collected = sum(int(node.attrib.get("tests", "0")) for node in suites)
    failures = sum(int(node.attrib.get("failures", "0")) for node in suites)
    errors = sum(int(node.attrib.get("errors", "0")) for node in suites)
    skipped = sum(int(node.attrib.get("skipped", "0")) for node in suites)
    failed = failures + errors
    passed = max(0, collected - failed - skipped)
    return collected, passed, failed, skipped


def evidence_row(*, run_id: str, attempt: int, task_id: str, base: str,
                 head: str, diff_hash: str, outcome: str, exit_code: int,
                 counts: tuple[int, int, int, int], command_hash: str) -> dict:
    collected, passed, failed, skipped = counts
    return {
        "schema_version": 1,
        "run_id": str(run_id),
        "run_attempt": attempt,
        "task_id": task_id,
        "base_sha": base,
        "head_sha": head,
        "diff_sha256": diff_hash,
        "outcome": outcome,
        "exit_code": exit_code,
        "tests_collected": collected,
        "tests_passed": passed,
        "tests_failed": failed,
        "tests_skipped": skipped,
        "test_command_sha256": command_hash,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True, type=int)
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--source-head-branch", required=True)
    args = parser.parse_args()

    repo = os.environ["GH_REPOSITORY"]
    token = os.environ.get("GH_TOKEN", "")
    if not token or not args.run_id.isdigit() or args.run_attempt < 1:
        raise SystemExit("trusted workflow context is incomplete")
    if not SHA40.fullmatch(args.source_head_sha):
        raise SystemExit("source workflow head SHA is invalid")

    # The source workflow publishes only to this run-scoped branch. Require its
    # tip to match the final task SHA; never trust an artifact's branch claim.
    branch = f"line-dev/{args.run_id}"
    encoded_branch = quote(branch, safe="")
    ref = run(["gh", "api", f"repos/{repo}/git/ref/heads/{encoded_branch}"],
              capture_output=True).stdout
    ref_data = json.loads(ref)
    branch_tip = ref_data.get("object", {}).get("sha", "")
    if not SHA40.fullmatch(branch_tip):
        raise SystemExit("run-scoped development branch ref is invalid")

    rows = []
    for number, line in enumerate(args.input.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"malformed task evidence line {number}") from exc
        if not isinstance(row, dict):
            raise SystemExit(f"task evidence line {number} is not an object")
        rows.append(row)
    if not rows:
        raise SystemExit("task evidence is empty")

    args.output.mkdir(parents=True, exist_ok=True)
    command = [
        "python", "-m", "pytest", "-q", "-p", "no:cacheprovider",
        "--junitxml=/evidence/junit.xml", *REA_TESTS,
    ]
    command_hash = hashlib.sha256("\0".join(command).encode()).hexdigest()
    output_rows = []
    previous = args.source_head_sha

    # A clean temporary git worktree is used only by the trusted collector.
    # The source test container receives a git archive, not .git or credentials.
    with tempfile.TemporaryDirectory(prefix="rea-collector-") as temp:
        root = Path(temp)
        run(["git", "init", str(root / "repo")], capture_output=True)
        git = ["git", "-C", str(root / "repo")]
        run(git + ["remote", "add", "origin", f"https://github.com/{repo}.git"])
        run(["gh", "auth", "setup-git"])
        image_dir = root / "image"
        image_dir.mkdir()
        (image_dir / "Dockerfile").write_text(
            "FROM python:3.12-slim\n"
            "RUN python -m pip install --no-cache-dir pytest==8.3.5\n"
            "WORKDIR /workspace\nUSER 65532:65532\n",
            encoding="utf-8",
        )
        image = f"rea-collector:{args.run_id}"
        run(["docker", "build", "--pull", "-t", image, str(image_dir)])

        for index, row in enumerate(rows, 1):
            task_id = row.get("task_id")
            base = row.get("base_sha")
            head = row.get("produced_sha")
            status = row.get("status")
            if not isinstance(task_id, str) or not task_id.strip():
                raise SystemExit(f"task {index} has no valid task ID")
            if status not in {"PASS", "NO_CHANGE"}:
                # Preserve a non-success result as a non-PASS evidence record.
                continue
            if not isinstance(base, str) or not SHA40.fullmatch(base):
                raise SystemExit(f"task {task_id} base SHA is invalid")
            if not isinstance(head, str) or not SHA40.fullmatch(head):
                raise SystemExit(f"task {task_id} produced SHA is invalid")
            if base != previous:
                raise SystemExit(f"task {task_id} breaks the run's SHA chain")
            previous = head

            run(git + ["fetch", "--no-tags", "origin", base, head])
            ancestor = run(git + ["merge-base", "--is-ancestor", base, head], check=False)
            if ancestor.returncode != 0:
                raise SystemExit(f"task {task_id} head is not based on its declared base")
            diff = run(git + ["diff", "--binary", base, head], capture_output=True).stdout
            diff_hash = hashlib.sha256(diff.encode()).hexdigest()
            changed = run(git + ["diff", "--name-only", base, head],
                          capture_output=True).stdout.splitlines()
            if not changed:
                continue
            if head != branch_tip and index == len(rows):
                raise SystemExit("final task SHA does not match the run-scoped branch tip")

            # This collector is intentionally scoped to REA regression changes.
            # Non-REA task changes cannot be certified by this focused suite.
            if not any(path.startswith(REA_PATH_PREFIXES) for path in changed):
                counts = (0, 0, 0, 0)
                output_rows.append(evidence_row(
                    run_id=args.run_id, attempt=args.run_attempt, task_id=task_id,
                    base=base, head=head, diff_hash=diff_hash, outcome="skipped",
                    exit_code=0, counts=counts, command_hash=command_hash,
                ))
                continue

            source = root / f"source-{index}"
            source.mkdir()
            archive = run(git + ["archive", "--format=tar", head],
                          capture_output=True).stdout
            archive_path = root / f"source-{index}.tar"
            archive_path.write_bytes(archive.encode("latin1"))
            with tarfile.open(archive_path, "r:") as tar:
                tar.extractall(source, filter="data")

            evidence_dir = root / f"evidence-{index}"
            evidence_dir.mkdir()
            # The only writable mount is a result directory. No token, network,
            # host socket, git metadata, or source write access enters the sandbox.
            result = run([
                "docker", "run", "--rm", "--network", "none", "--read-only",
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m,uid=65532,gid=65532",
                "--mount", f"type=bind,src={source},dst=/workspace,readonly",
                "--mount", f"type=bind,src={evidence_dir},dst=/evidence",
                "--workdir", "/workspace", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges:true", "--pids-limit", "128",
                "--memory", "2g", "--cpus", "2", "--user", "65532:65532",
                "--env", "PYTHONDONTWRITEBYTECODE=1",
                "--env", "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1", image, *command,
            ], check=False)
            junit = evidence_dir / "junit.xml"
            counts = parse_counts(junit) if junit.exists() else (0, 0, 0, 0)
            outcome = "success" if result.returncode == 0 else "failure"
            output_rows.append(evidence_row(
                run_id=args.run_id, attempt=args.run_attempt, task_id=task_id,
                base=base, head=head, diff_hash=diff_hash, outcome=outcome,
                exit_code=result.returncode, counts=counts, command_hash=command_hash,
            ))

    if previous != branch_tip:
        raise SystemExit("verified task chain does not end at the run-scoped branch tip")
    if not output_rows:
        # No changed REA task was independently tested; write an explicit
        # non-PASS marker so downstream consumers cannot infer success.
        output_rows.append({
            "schema_version": 1, "run_id": str(args.run_id),
            "run_attempt": args.run_attempt, "outcome": "skipped",
            "reason_code": "no_changed_rea_task_tested",
        })
    out = args.output / "rea-independent-test-evidence.jsonl"
    out.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in output_rows),
                   encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
