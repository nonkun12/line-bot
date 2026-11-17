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
from pathlib import Path
from urllib.parse import quote

SHA40 = re.compile(r"[0-9a-f]{40}")
SHA64 = re.compile(r"[0-9a-f]{64}")
REA_TESTS = (
    "tests/test_rea_artifact_evaluator.py",
    "tests/test_rea_independent_test_evidence.py",
    "tests/test_rea_independent_collector.py",
)
REA_PATH_PREFIXES = ("core/rea_", "scripts/rea_", "tests/test_rea_")


def run(command: list[str], *, check: bool = True, **kwargs):
    return subprocess.run(command, check=check, text=True, **kwargs)


def run_bytes(command: list[str]) -> bytes:
    return subprocess.run(command, check=True, capture_output=True).stdout


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def captured_output_text(output: object) -> str:
    """Normalize subprocess output from text=True and byte-oriented callers."""
    if isinstance(output, str):
        return output
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return ""


def parse_counts(output: str) -> tuple[int, int, int, int]:
    """Parse pytest's terminal summary captured outside the sandbox."""
    matches = re.findall(
        r"(?:(\d+)\s+passed)?(?:,\s*)?(?:(\d+)\s+failed)?"
        r"(?:,\s*)?(?:(\d+)\s+errors?)?(?:,\s*)?"
        r"(?:(\d+)\s+skipped)?(?:,\s*)?(?:(\d+)\s+xfailed)?"
        r"(?:,\s*)?(?:(\d+)\s+xpassed)?(?:,\s*\d+\s+warnings?)?"
        r"\s+in\s+[0-9.]+s",
        output,
    )
    if not matches:
        return 0, 0, 0, 0
    # On successful pytest runs, test stdout is captured. Use the first terminal
    # summary so late atexit output from candidate code cannot replace it.
    passed, failed, errors, skipped, xfailed, xpassed = (
        int(value or 0) for value in matches[0]
    )
    skipped += xfailed + xpassed
    collected = passed + failed + errors + skipped
    return collected, passed, failed + errors, skipped


def validate_task_rows(rows: list[dict]) -> None:
    """Validate task rows while preserving run-level non-success outcomes."""
    if not rows or len(rows) > 4:
        raise SystemExit("source task count is outside the allowed range")
    seen: set[str] = set()
    for index, row in enumerate(rows, 1):
        status = row.get("status")
        if status not in {"PASS", "NO_CHANGE", "FAIL", "HOLD", "BLOCKED", "STOPPED", "NOT_RUN"}:
            raise SystemExit(f"task {index} has an unsupported status")
        task_id = row.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            if status not in {"NOT_RUN", "BLOCKED"}:
                raise SystemExit(f"task {index} has no valid task ID")
            continue
        if task_id in seen:
            raise SystemExit("source task IDs are not unique")
        seen.add(task_id)
        base = row.get("base_sha")
        head = row.get("produced_sha")
        if status in {"PASS", "NO_CHANGE"}:
            if not isinstance(base, str) or SHA40.fullmatch(base) is None:
                raise SystemExit(f"successful task {task_id} has invalid base SHA")
            if not isinstance(head, str) or SHA40.fullmatch(head) is None:
                raise SystemExit(f"successful task {task_id} has invalid produced SHA")


def no_candidate_reason(rows: list[dict]) -> str:
    """Distinguish expected no-work runs from non-success task outcomes."""
    blocking = {"FAIL", "HOLD", "BLOCKED", "STOPPED"}
    if any(row.get("status") in blocking for row in rows):
        return "source_non_success_task_without_verifiable_commit_identity"
    return "no_changed_task_commits"


def is_candidate_task_row(row: object) -> bool:
    """Keep changed tasks and every non-success task for downstream verification."""
    if not isinstance(row, dict):
        return False
    task_id = row.get("task_id")
    base = row.get("base_sha")
    head = row.get("produced_sha")
    if not isinstance(task_id, str) or not task_id.strip():
        return False
    if not isinstance(base, str) or SHA40.fullmatch(base) is None:
        return False
    if not isinstance(head, str) or SHA40.fullmatch(head) is None:
        return False
    return base != head or row.get("status") not in {"PASS", "NO_CHANGE"}


def prepare_trusted_harness(harness: Path) -> None:
    """Stage default-branch tests and a runner outside the untrusted source tree."""
    trusted_root = Path(__file__).resolve().parents[1]
    tests_root = harness / "tests"
    tests_root.mkdir(parents=True, exist_ok=True)
    for relative in REA_TESTS:
        trusted_test = trusted_root / relative
        if not trusted_test.is_file() or trusted_test.is_symlink():
            raise SystemExit(f"trusted regression test is unavailable: {relative}")
        shutil.copyfile(trusted_test, tests_root / Path(relative).name)
    test_args = ", ".join(f'"/harness/tests/{Path(name).name}"' for name in REA_TESTS)
    runner = (
        "import sys, types\n"
        "import pytest\n"
        "core_package = types.ModuleType('core')\n"
        "core_package.__path__ = ['/workspace/core']\n"
        "sys.modules['core'] = core_package\n"
        "scripts_package = types.ModuleType('scripts')\n"
        "scripts_package.__path__ = ['/workspace/scripts']\n"
        "sys.modules['scripts'] = scripts_package\n"
        "sys.path.append('/workspace')\n"
        "raise SystemExit(pytest.main(['-q', '-p', 'no:cacheprovider', "
        "'--noconftest', "
        + test_args + "]))\n"
    )
    (harness / "runner.py").write_text(runner, encoding="utf-8")




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
    parser.add_argument("--default-branch", required=True)
    args = parser.parse_args()

    if not args.default_branch or args.source_head_branch != args.default_branch:
        raise SystemExit("source workflow did not run from the repository default branch")
    repo = os.environ["GH_REPOSITORY"]
    token = os.environ.get("GH_TOKEN", "")
    if not token or not args.run_id.isdigit() or args.run_attempt < 1:
        raise SystemExit("trusted workflow context is incomplete")
    if not SHA40.fullmatch(args.source_head_sha):
        raise SystemExit("source workflow head SHA is invalid")

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
    validate_task_rows(rows)

    args.output.mkdir(parents=True, exist_ok=True)
    candidate_rows = [row for row in rows if is_candidate_task_row(row)]
    if not candidate_rows:
        marker = {
            "schema_version": 1, "run_id": str(args.run_id),
            "run_attempt": args.run_attempt, "outcome": "skipped",
            "reason_code": no_candidate_reason(rows),
        }
        (args.output / "rea-independent-test-evidence.jsonl").write_text(
            json.dumps(marker, sort_keys=True) + "\n", encoding="utf-8"
        )
        context = {
            "schema_version": 1,
            "collector_run_id": os.environ.get("GITHUB_RUN_ID", ""),
            "source_run_id": str(args.run_id),
            "source_run_attempt": args.run_attempt,
            "source_head_sha": args.source_head_sha,
            "source_head_branch": args.source_head_branch,
            "expected_tasks": [],
        }
        (args.output / "collector-context.json").write_text(
            json.dumps(context, sort_keys=True) + "\n", encoding="utf-8"
        )
        return 0

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
    command = ["python", "/harness/runner.py"]
    trusted_root = Path(__file__).resolve().parents[1]
    harness_digest = hashlib.sha256()
    for relative in REA_TESTS:
        trusted_test = trusted_root / relative
        if not trusted_test.is_file() or trusted_test.is_symlink():
            raise SystemExit(f"trusted regression test is unavailable: {relative}")
        harness_digest.update(relative.encode("utf-8") + b"\0")
        harness_digest.update(trusted_test.read_bytes())
    harness_digest.update(Path(__file__).read_bytes())
    command_hash = hashlib.sha256(
        "\0".join(command).encode() + b"\0" + harness_digest.digest()
    ).hexdigest()
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
        run(git + ["fetch", "--no-tags", "origin", f"refs/heads/{branch}"])
        fetched_tip = run(git + ["rev-parse", "FETCH_HEAD"], capture_output=True).stdout.strip()
        if fetched_tip != branch_tip:
            raise SystemExit("fetched run branch does not match the trusted API ref")
        image_dir = root / "image"
        image_dir.mkdir()
        (image_dir / "Dockerfile").write_text(
            "FROM python:3.12-slim\n"
            "RUN python -m pip install --no-cache-dir pytest==8.3.5 pluggy==1.7.0 packaging==26.3 iniconfig==2.3.1\n"
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
            if status not in {"PASS", "NO_CHANGE"} and not is_candidate_task_row(row):
                output_rows.append({
                    "schema_version": 1,
                    "run_id": str(args.run_id),
                    "run_attempt": args.run_attempt,
                    "outcome": "skipped",
                    "reason_code": "source_non_success_task_without_verifiable_commit_identity",
                })
                continue
            if not isinstance(task_id, str) or not task_id.strip():
                raise SystemExit(f"task {index} has no valid task ID")
            if not isinstance(base, str) or not SHA40.fullmatch(base):
                raise SystemExit(f"task {task_id} base SHA is invalid")
            if not isinstance(head, str) or not SHA40.fullmatch(head):
                raise SystemExit(f"task {task_id} produced SHA is invalid")
            if base != previous:
                raise SystemExit(f"task {task_id} breaks the run's SHA chain")
            previous = head

            run(git + ["cat-file", "-e", f"{base}^{{commit}}"])
            run(git + ["cat-file", "-e", f"{head}^{{commit}}"])
            ancestor = run(git + ["merge-base", "--is-ancestor", base, head], check=False)
            if ancestor.returncode != 0:
                raise SystemExit(f"task {task_id} head is not based on its declared base")
            diff = run_bytes(git + ["diff", "--binary", base, head])
            diff_hash = hashlib.sha256(diff).hexdigest()
            changed = run(git + ["diff", "--name-only", base, head],
                          capture_output=True).stdout.splitlines()
            if status not in {"PASS", "NO_CHANGE"}:
                # Never silently discard failed, held, or blocked task outcomes.
                # Emit identity-bound non-PASS evidence so the trusted post-run
                # validator must classify the task as FAIL/BLOCKED/HOLD.
                output_rows.append(evidence_row(
                    run_id=args.run_id, attempt=args.run_attempt, task_id=task_id,
                    base=base, head=head, diff_hash=diff_hash,
                    outcome=("failure" if status == "FAIL" else "skipped"),
                    exit_code=(row.get("exit_code") if isinstance(row.get("exit_code"), int)
                               and not isinstance(row.get("exit_code"), bool)
                               and row.get("exit_code") >= 0 else 1),
                    counts=(0, 0, 0, 0), command_hash=command_hash,
                ))
                continue
            if not changed:
                continue
            if head != branch_tip and index == len(rows):
                raise SystemExit("final task SHA does not match the run-scoped branch tip")

            # This collector is intentionally scoped to REA regression changes.
            # Non-REA task changes cannot be certified by this focused suite.
            if not any(path.startswith(REA_PATH_PREFIXES) for path in changed):
                # This collector certifies only REA-focused regression tests.
                # Unrelated tasks are intentionally outside its evidence scope.
                continue

            source = root / f"source-{index}"
            source.mkdir()
            archive = run_bytes(git + ["archive", "--format=tar", head])
            archive_path = root / f"source-{index}.tar"
            archive_path.write_bytes(archive)
            with tarfile.open(archive_path, "r:") as tar:
                tar.extractall(source, filter="data")
            # Keep trusted tests and their runner outside the task source tree.
            harness = root / f"harness-{index}"
            harness.mkdir()
            prepare_trusted_harness(harness)

            # No writable host mount is exposed to task code. The trusted host
            # captures stdout/exit status and creates the evidence record itself.
            result = run([
                "docker", "run", "--rm", "--network", "none", "--read-only",
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m,uid=65532,gid=65532",
                "--mount", f"type=bind,src={source},dst=/workspace,readonly",
                "--mount", f"type=bind,src={harness},dst=/harness,readonly",
                "--workdir", "/tmp", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges:true", "--pids-limit", "128",
                "--memory", "2g", "--cpus", "2", "--user", "65532:65532",
                "--env", "PYTHONDONTWRITEBYTECODE=1",
                "--env", "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1", image, *command,
            ], check=False, capture_output=True)
            output = captured_output_text(result.stdout)
            counts = parse_counts(output)
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
    context = {
        "schema_version": 1,
        "collector_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "source_run_id": str(args.run_id),
        "source_run_attempt": args.run_attempt,
        "source_head_sha": args.source_head_sha,
        "source_head_branch": args.source_head_branch,
        "expected_tasks": [
            {
                key: row[key]
                for key in (
                    "run_id", "run_attempt", "task_id", "base_sha",
                    "head_sha", "diff_sha256", "test_command_sha256",
                )
                if key in row
            }
            for row in output_rows if "task_id" in row
        ],
    }
    (args.output / "collector-context.json").write_text(
        json.dumps(context, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
