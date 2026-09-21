"""Concrete LINE development adapters for the bounded multi-agent runtime.

This module connects the existing guarded file-editing primitives to the
provider-neutral runtime. It deliberately keeps GitHub/LINE transport outside
this runtime itself.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .agent_runtime import RepairPlanner, RuntimeReport
from .control_tower import ControlTower
from .creator_critic_runtime import build_creator_critic_loop
from .self_improvement import SelfImprovementEngine
from .self_improvement_cycle import SelfImprovementCycleResult, run_self_improvement_cycle
from .execution_safety import GitWorktreeSafetyGate
from .multi_agent import AgentResult, AgentRole, AgentTask
from .quality_runtime import QualityRuntime
from scripts import line_development_worker_v2 as worker


@dataclass
class DevelopmentState:
    client: object
    instruction: str
    chosen: str | None = None
    plan: dict | None = None
    touched: list[str] | None = None
    test_output: str = ""
    tests_passed: bool = False
    baseline_status: str = ""
    verified_sha: str = ""
    verified_diff: str = ""
    verified_test_output: str = ""


def _fallback_safe_target(files: list[str]) -> str | None:
    """Return a deterministic, test-focused target when model selection fails."""
    preferred = (
        "tests/test_management_router.py",
        "tests/test_agent_runtime.py",
        "tests/test_line_development_runtime.py",
    )
    available = set(files)
    for path in preferred:
        if path in available and not worker.is_protected(path):
            return path
    return None


def _rollback_to_clean_baseline(baseline_sha: str) -> bool:
    """Restore the previously verified clean baseline and remove untracked files."""
    reset = worker.run(["git", "reset", "--hard", baseline_sha])
    if reset.returncode != 0:
        return False
    clean = worker.run(["git", "clean", "-fd"])
    return clean.returncode == 0


def _explicit_comment_plan(instruction: str, chosen: str) -> dict | None:
    """Build deterministic plans for explicit one-line comment E2E requests."""
    if chosen != "line_development.py":
        return None
    if not re.search(r"コメント.*(?:1行|一行)|(?:1行|一行).*コメント", instruction, re.IGNORECASE | re.DOTALL):
        return None
    match = re.search(r"[「『\"']([^」』\"']+)[」』\"']", instruction)
    if not match:
        return None
    comment_text = re.sub(r"[\r\n]+", " ", match.group(1)).strip()[:120]
    if not comment_text:
        return None
    target = worker.ROOT / chosen
    text = target.read_text(encoding="utf-8")
    marker = f"# {comment_text}"
    if marker in text:
        return {"no_change": True, "source": "deterministic_self_test"}
    match_anchor = re.search(r"^(_WORKFLOW_FILE\s*=\s*\"[^\"\n]+\"\n)", text, re.MULTILINE)
    if match_anchor:
        anchor = match_anchor.group(1)
        return {
            "no_change": False,
            "source": "deterministic_self_test",
            "changes": [{"file": chosen, "old": anchor, "new": anchor + marker + "\n"}],
        }
    line_end = text.find("\n")
    if line_end < 0:
        return {"no_change": False, "source": "deterministic_self_test", "changes": [{"file": chosen, "old": text, "new": text + f"\n{marker}\n"}]}
    anchor = text[: line_end + 1]
    return {"no_change": False, "source": "deterministic_self_test", "changes": [{"file": chosen, "old": anchor, "new": anchor + marker + "\n"}]}


def _is_deterministic_comment_request(instruction: str, chosen: str | None) -> bool:
    return chosen == "line_development.py" and re.search(r"コメント.*(?:1行|一行)|(?:1行|一行).*コメント", instruction, re.IGNORECASE | re.DOTALL) is not None


def _self_improvement_history_path() -> Path:
    raw = os.environ.get(
        "SELF_IMPROVEMENT_HISTORY_PATH",
        "/tmp/line-bot-self-improvement.jsonl",
    ).strip()
    return Path(raw or "/tmp/line-bot-self-improvement.jsonl")


def _self_improvement_creator_critic_enabled() -> bool:
    return os.environ.get(
        "SELF_IMPROVEMENT_CREATOR_CRITIC",
        "true",
    ).strip().lower() in {"1", "true", "yes", "on"}


def observe_self_improvement(
    report: RuntimeReport,
    target_path: str,
) -> SelfImprovementCycleResult | None:
    """Feed one real development report into the bounded improvement loop.

    This is an observation/approval boundary only. Generated proposals and
    approved handoffs are never executed from this function.
    """
    try:
        feedback_engine = SelfImprovementEngine()
        creator_critic = (
            build_creator_critic_loop(max_iterations=1)
            if _self_improvement_creator_critic_enabled()
            else None
        )
        control_tower = ControlTower(
            feedback_engine=feedback_engine,
            creator_critic=creator_critic,
        )
        result = run_self_improvement_cycle(
            report,
            _self_improvement_history_path(),
            target_paths=(target_path,),
            control_tower=control_tower,
        )
        approved = len(result.approved_proposals)
        handoff_note = f", approved_handoffs={approved}" if approved else ""
        print(
            "[SELF-IMPROVEMENT] "
            f"signals={len(result.new_signals)}, "
            f"patterns={len(result.analysis.recurring_patterns)}, "
            f"proposals={len(result.proposals)}"
            f"{handoff_note}",
            flush=True,
        )
        return result
    except Exception as exc:
        # Improvement observation must never turn a validated development result
        # into an unrelated deployment failure.
        print(
            f"[SELF-IMPROVEMENT] observation skipped: {type(exc).__name__}: {exc}",
            flush=True,
        )
        return None


class DevelopmentExecutor:
    """Execute concrete development roles against one guarded worktree."""

    def __init__(self, state: DevelopmentState) -> None:
        self.state = state

    def execute(self, task: AgentTask) -> AgentResult:
        try:
            if task.role is AgentRole.MANAGER:
                files = worker.repo_files()
                chosen = worker.choose_file(self.state.client, self.state.instruction, files)
                if not chosen:
                    chosen = _fallback_safe_target(files)
                if not chosen:
                    return AgentResult(task.task_id, False, "manager could not select a safe target")
                self.state.chosen = chosen
                return AgentResult(task.task_id, True, f"selected {chosen}", frozenset({chosen}))
            if self.state.chosen is None:
                return AgentResult(task.task_id, False, "manager selection missing")
            if task.role is AgentRole.IMPLEMENTER:
                explicit_comment_plan = _explicit_comment_plan(self.state.instruction, self.state.chosen)
                comment_plan = None if explicit_comment_plan is not None else worker.build_comment_test_plan(self.state.instruction, self.state.chosen)
                plan = explicit_comment_plan if explicit_comment_plan is not None else comment_plan if comment_plan is not None else worker.build_plan(self.state.client, self.state.instruction, self.state.chosen, worker.context_for(self.state.chosen))
                ok, detail = worker.validate_plan(plan, self.state.chosen)
                if not ok:
                    return AgentResult(task.task_id, False, f"implementation plan rejected: {detail}")
                if detail == "no_change":
                    self.state.plan = plan; self.state.touched = []
                    return AgentResult(task.task_id, True, "no safe change required")
                applied, detail, touched = worker.apply_plan(plan)
                if not applied:
                    worker.restore(touched)
                    return AgentResult(task.task_id, False, f"apply failed: {detail}")
                self.state.plan = plan; self.state.touched = touched
                return AgentResult(task.task_id, True, "guarded change applied", frozenset(touched))
            if task.role is AgentRole.TESTER:
                passed, output = worker.run_tests(self.state.touched or [])
                self.state.tests_passed = passed; self.state.test_output = output
                return AgentResult(task.task_id, passed, output[-4000:], frozenset(self.state.touched or []))
            if task.role is AgentRole.DEBUGGER:
                if _is_deterministic_comment_request(self.state.instruction, self.state.chosen):
                    return AgentResult(task.task_id, True, "deterministic debug retry; no LLM JSON parsing")
                worker.restore(self.state.touched or [])
                failure_context = task.instruction
                if self.state.test_output:
                    failure_context = f"{failure_context}\nPrevious test output:\n{self.state.test_output[-4000:]}"
                plan = worker.build_plan(self.state.client, self.state.instruction, self.state.chosen, worker.context_for(self.state.chosen), failure_context)
                ok, detail = worker.validate_plan(plan, self.state.chosen)
                if not ok or detail == "no_change":
                    return AgentResult(task.task_id, False, f"debug plan rejected: {detail}")
                applied, detail, touched = worker.apply_plan(plan)
                if not applied:
                    worker.restore(touched)
                    return AgentResult(task.task_id, False, f"debug apply failed: {detail}")
                self.state.plan = plan; self.state.touched = touched
                return AgentResult(task.task_id, True, "debug fix applied", frozenset(touched))
            if task.role is AgentRole.REFACTORER:
                if _is_deterministic_comment_request(self.state.instruction, self.state.chosen):
                    return AgentResult(task.task_id, True, "no refactor needed for deterministic comment change")
                plan = worker.build_plan(self.state.client, f"Refactor the current implementation for clarity, maintainability, and duplication reduction. Preserve behavior and satisfy the original request. Original request: {self.state.instruction}", self.state.chosen, worker.context_for(self.state.chosen), self.state.test_output)
                ok, detail = worker.validate_plan(plan, self.state.chosen)
                if not ok:
                    return AgentResult(task.task_id, False, f"refactor plan rejected: {detail}")
                if detail == "no_change":
                    return AgentResult(task.task_id, True, "no refactor change required")
                applied, detail, touched = worker.apply_plan(plan)
                if not applied:
                    worker.restore(touched)
                    return AgentResult(task.task_id, False, f"refactor apply failed: {detail}")
                self.state.plan = plan; self.state.touched = touched
                return AgentResult(task.task_id, True, "refactor applied", frozenset(touched))
            if task.role is AgentRole.REVIEWER:
                status = worker.run(["git", "diff", "--check"])
                if status.returncode != 0:
                    return AgentResult(task.task_id, False, f"git diff --check failed: {status.stderr[-3000:]}")
                diff = worker.run(["git", "diff", "--", *(self.state.touched or [])])
                if diff.returncode != 0:
                    return AgentResult(task.task_id, False, f"git diff failed: {diff.stderr[-3000:]}")
                if not diff.stdout.strip() and self.state.touched:
                    return AgentResult(task.task_id, False, "reviewer found no resulting diff")
                return AgentResult(task.task_id, True, "review gate passed", frozenset(self.state.touched or []))
            if task.role is AgentRole.REPAIRER:
                if _is_deterministic_comment_request(self.state.instruction, self.state.chosen):
                    return AgentResult(task.task_id, True, "deterministic repair retry; no LLM JSON parsing")
                plan = worker.build_plan(self.state.client, self.state.instruction, self.state.chosen, worker.context_for(self.state.chosen), self.state.test_output)
                ok, detail = worker.validate_plan(plan, self.state.chosen)
                if not ok or detail == "no_change":
                    return AgentResult(task.task_id, False, f"repair plan rejected: {detail}")
                worker.restore(self.state.touched or [])
                applied, detail, touched = worker.apply_plan(plan)
                if not applied:
                    worker.restore(touched)
                    return AgentResult(task.task_id, False, f"repair apply failed: {detail}")
                self.state.plan = plan; self.state.touched = touched
                return AgentResult(task.task_id, True, "repair applied", frozenset(touched))
            if task.role is AgentRole.INTEGRATOR:
                status = worker.run(["git", "status", "--short"])
                if status.returncode != 0:
                    return AgentResult(task.task_id, False, status.stderr[-3000:])
                if self.state.touched and not status.stdout.strip():
                    return AgentResult(task.task_id, False, "integration gate found no working-tree change")
                return AgentResult(task.task_id, True, "integration gate passed", frozenset(self.state.touched or []))
            return AgentResult(task.task_id, False, f"unsupported role: {task.role.value}")
        except Exception as exc:
            return AgentResult(task.task_id, False, f"{type(exc).__name__}: {exc}")


class DevelopmentRepairPlanner(RepairPlanner):
    def __init__(self, state: DevelopmentState) -> None:
        self.state = state
    def repair_task(self, failed_task: AgentTask, result: AgentResult, attempt: int) -> AgentTask:
        mode = "Use deterministic retry; do not call an LLM or parse JSON." if _is_deterministic_comment_request(self.state.instruction, self.state.chosen) else "Use the normal guarded repair planner."
        return AgentTask(task_id=f"repair:{attempt}:{failed_task.task_id}", role=AgentRole.REPAIRER, instruction=f"{mode} Repair after {failed_task.role.value} failure: {result.summary[-1500:]}", resources=failed_task.resources)


def execute(instruction: str) -> int:
    """Run one real guarded development request through the quality pipeline."""
    client = worker.Groq(api_key=os.environ["GROQ_API_KEY"])
    state = DevelopmentState(client=client, instruction=instruction)
    executor = DevelopmentExecutor(state)
    tasks = (
        AgentTask("manager", AgentRole.MANAGER, "Select one safe implementation target.", resources=frozenset({"target-selection"})),
        AgentTask("implementer", AgentRole.IMPLEMENTER, "Implement the explicit LINE development request.", resources=frozenset({"working-tree"}), depends_on=("manager",)),
        AgentTask("tester", AgentRole.TESTER, "Run guarded compile and full pytest checks.", resources=frozenset({"working-tree"}), depends_on=("implementer",)),
        AgentTask("reviewer", AgentRole.REVIEWER, "Review the resulting diff and gate the change.", resources=frozenset({"working-tree"}), depends_on=("tester",)),
        AgentTask("integrator", AgentRole.INTEGRATOR, "Run the final integration gate.", resources=frozenset({"working-tree"}), depends_on=("reviewer",)),
    )
    # Manager is read-only target selection. Establish a clean baseline immediately
    # before any file-changing role so pre-existing dirty state cannot be mistaken
    # for autonomous work.
    manager_result = executor.execute(tasks[0])
    if not manager_result.success:
        print(f"Manager selection failed: {manager_result.summary}", flush=True)
        return 1
    if state.chosen is None:
        print("Manager produced no target.", flush=True)
        return 1
    baseline = worker.run(["git", "status", "--porcelain=v1", "--untracked-files=all"])
    if baseline.returncode != 0:
        print(f"Baseline status failed: {baseline.stderr[-2000:]}", flush=True)
        return 1
    state.baseline_status = baseline.stdout
    if baseline.stdout.strip():
        print("Worktree is not clean before autonomous execution; refusing to proceed.", flush=True)
        return 1
    head = worker.run(["git", "rev-parse", "HEAD"])
    if head.returncode != 0 or not head.stdout.strip():
        print(f"Baseline SHA capture failed: {head.stderr[-2000:]}", flush=True)
        return 1
    baseline_sha = head.stdout.strip()
    safety_gate = GitWorktreeSafetyGate(worker.ROOT, baseline_sha, (state.chosen,))
    runtime = QualityRuntime(
        {
            AgentRole.IMPLEMENTER: executor,
            AgentRole.TESTER: executor,
            AgentRole.DEBUGGER: executor,
            AgentRole.REFACTORER: executor,
            AgentRole.REVIEWER: executor,
            AgentRole.REPAIRER: executor,
            AgentRole.INTEGRATOR: executor,
        },
        max_rounds=3,
        execution_safety_gate=safety_gate,
        allowed_paths=(state.chosen,),
    )
    try:
        report = runtime.run(tasks[1:])
    except Exception as exc:
        _rollback_to_clean_baseline(baseline_sha)
        print(f"Multi-agent development failed closed: {type(exc).__name__}: {exc}", flush=True)
        return 1
    print(f"[manager] {tasks[0].task_id}: {manager_result.summary[-1500:]}", flush=True)
    for item in report.completed:
        print(f"[{item.task.role.value}] {item.task.task_id}: {item.result.summary[-1500:]}", flush=True)
    improvement_result = observe_self_improvement(report, state.chosen)
    if not report.success or not report.integration_ready:
        _rollback_to_clean_baseline(baseline_sha)
        print(f"Multi-agent development failed: {report.error or report.failed_task_id}", flush=True)
        return 1
    touched = state.touched or []
    if not touched:
        _rollback_to_clean_baseline(baseline_sha)
        print("Multi-agent development produced no file change.", flush=True)
        return 1
    # Freeze the exact worktree that passed TEST + REVIEW + Safety Gate.
    # The later commit/PR must contain exactly this verified diff.
    verified_head = worker.run(["git", "rev-parse", "HEAD"])
    verified_diff = worker.run(["git", "diff", "--binary", baseline_sha, "HEAD"])
    verified_status = worker.run(["git", "status", "--porcelain=v1", "--untracked-files=all"])
    if (
        verified_head.returncode != 0
        or verified_diff.returncode != 0
        or verified_status.returncode != 0
        or verified_status.stdout.strip()
    ):
        _rollback_to_clean_baseline(baseline_sha)
        print("Final verification snapshot failed closed.", flush=True)
        return 1
    state.verified_sha = verified_head.stdout.strip()
    state.verified_diff = verified_diff.stdout
    state.verified_test_output = state.test_output

    branch = f"line-dev/{os.environ.get('GITHUB_RUN_ID', 'manual')}"
    identity = ["-c", "user.name=github-actions[bot]", "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com"]
    add = worker.run(["git", "add", "--", *touched])
    if add.returncode != 0:
        worker.restore(touched); print(add.stderr[-2000:], flush=True); return 1
    status = worker.run(["git", "status", "--short"])
    if status.returncode != 0 or not status.stdout.strip():
        worker.restore(touched); print("No changes to commit.", flush=True); return 1
    commit = worker.run(["git", *identity, "commit", "-m", "feat: LINE development request"])
    if commit.returncode != 0:
        worker.restore(touched); print(commit.stderr[-2000:], flush=True); return 1
    commit_sha = worker.run(["git", "rev-parse", "HEAD"])
    committed_diff = worker.run(["git", "diff", "--binary", baseline_sha, "HEAD"])
    if (
        commit_sha.returncode != 0
        or committed_diff.returncode != 0
        or commit_sha.stdout.strip() != state.verified_sha
        or committed_diff.stdout != state.verified_diff
    ):
        _rollback_to_clean_baseline(baseline_sha)
        print("Committed artifact does not match the verified SHA/diff; refusing to publish.", flush=True)
        return 1

    checkout = worker.run(["git", "checkout", "-B", branch])
    if checkout.returncode != 0:
        print(checkout.stderr[-2000:], flush=True); return 1
    push = worker.run(["git", "push", "--set-upstream", "origin", branch])
    if push.returncode != 0:
        print(push.stderr[-2000:], flush=True); return 1
    print(f"Development branch pushed: {branch}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(execute(os.environ.get("DEV_INSTRUCTION", "").strip()[:worker.MAX_INSTRUCTION_LENGTH]))
