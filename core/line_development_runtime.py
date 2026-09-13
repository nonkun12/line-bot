"""Concrete LINE development adapters for the bounded multi-agent runtime.

This module connects the existing guarded file-editing primitives to the
provider-neutral runtime. It deliberately keeps GitHub/LINE transport outside
the runtime itself.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .agent_runtime import MultiAgentRuntime, RepairPlanner
from .multi_agent import AgentResult, AgentRole, AgentTask
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


def _explicit_comment_plan(instruction: str, chosen: str) -> dict | None:
    """Build deterministic plans for explicit one-line comment E2E requests."""
    if chosen != "tests/test_line_development.py":
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
        return {"no_change": True}
    return {
        "no_change": False,
        "changes": [{
            "file": chosen,
            "old": text,
            "new": text.rstrip() + f"\n\n{marker}\n",
        }],
    }


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
                    return AgentResult(task.task_id, False, "manager could not select a safe target")
                self.state.chosen = chosen
                return AgentResult(task.task_id, True, f"selected {chosen}", frozenset({chosen}))

            if self.state.chosen is None:
                return AgentResult(task.task_id, False, "manager selection missing")

            if task.role is AgentRole.IMPLEMENTER:
                comment_plan = worker.build_comment_test_plan(self.state.instruction, self.state.chosen)
                explicit_comment_plan = _explicit_comment_plan(self.state.instruction, self.state.chosen)
                plan = (
                    comment_plan
                    if comment_plan is not None
                    else explicit_comment_plan
                    if explicit_comment_plan is not None
                    else worker.build_plan(
                        self.state.client,
                        self.state.instruction,
                        self.state.chosen,
                        worker.context_for(self.state.chosen),
                    )
                )
                ok, detail = worker.validate_plan(plan, self.state.chosen)
                if not ok:
                    return AgentResult(task.task_id, False, f"implementation plan rejected: {detail}")
                if detail == "no_change":
                    self.state.plan = plan
                    self.state.touched = []
                    return AgentResult(task.task_id, True, "no safe change required")
                applied, detail, touched = worker.apply_plan(plan)
                if not applied:
                    worker.restore(touched)
                    return AgentResult(task.task_id, False, f"apply failed: {detail}")
                self.state.plan = plan
                self.state.touched = touched
                return AgentResult(task.task_id, True, "guarded change applied", frozenset(touched))

            if task.role is AgentRole.TESTER:
                passed, output = worker.run_tests(self.state.touched or [])
                self.state.tests_passed = passed
                self.state.test_output = output
                return AgentResult(task.task_id, passed, output[-4000:], frozenset(self.state.touched or []))

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
                plan = worker.build_plan(
                    self.state.client,
                    self.state.instruction,
                    self.state.chosen,
                    worker.context_for(self.state.chosen),
                    self.state.test_output,
                )
                ok, detail = worker.validate_plan(plan, self.state.chosen)
                if not ok or detail == "no_change":
                    return AgentResult(task.task_id, False, f"repair plan rejected: {detail}")
                worker.restore(self.state.touched or [])
                applied, detail, touched = worker.apply_plan(plan)
                if not applied:
                    worker.restore(touched)
                    return AgentResult(task.task_id, False, f"repair apply failed: {detail}")
                self.state.plan = plan
                self.state.touched = touched
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
        return AgentTask(
            task_id=f"repair:{attempt}:{failed_task.task_id}",
            role=AgentRole.REPAIRER,
            instruction=f"Repair after {failed_task.role.value} failure: {result.summary[-1500:]}",
            resources=failed_task.resources,
        )


def execute(instruction: str) -> int:
    """Run one real guarded development request through all runtime roles."""
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
    runtime = MultiAgentRuntime(
        {
            AgentRole.MANAGER: executor,
            AgentRole.IMPLEMENTER: executor,
            AgentRole.TESTER: executor,
            AgentRole.REVIEWER: executor,
            AgentRole.REPAIRER: executor,
            AgentRole.INTEGRATOR: executor,
        },
        max_workers=1,
        max_rounds=3,
    )
    report = runtime.run_development(tasks, repair_planner=DevelopmentRepairPlanner(state))
    for item in report.completed:
        print(f"[{item.task.role.value}] {item.task.task_id}: {item.result.summary[-1500:]}", flush=True)
    if not report.success or not report.integration_ready:
        worker.restore(state.touched or [])
        print(f"Multi-agent development failed: {report.error or report.failed_task_id}", flush=True)
        return 1

    touched = state.touched or []
    if not touched:
        print("Multi-agent development produced no file change.", flush=True)
        return 1

    branch = f"line-dev/{os.environ.get('GITHUB_RUN_ID', 'manual')}"
    worker.run(["git", "config", "user.name", "github-actions[bot]"])
    worker.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"])
    add = worker.run(["git", "add", "--", *touched])
    if add.returncode != 0:
        worker.restore(touched)
        print(add.stderr[-2000:], flush=True)
        return 1
    status = worker.run(["git", "status", "--short"])
    if status.returncode != 0 or not status.stdout.strip():
        worker.restore(touched)
        print("No changes to commit.", flush=True)
        return 1
    commit = worker.run(["git", "commit", "-m", "feat: LINE development request"])
    if commit.returncode != 0:
        worker.restore(touched)
        print(commit.stderr[-2000:], flush=True)
        return 1
    checkout = worker.run(["git", "checkout", "-B", branch])
    if checkout.returncode != 0:
        print(checkout.stderr[-2000:], flush=True)
        return 1
    push = worker.run(["git", "push", "--set-upstream", "origin", branch])
    if push.returncode != 0:
        print(push.stderr[-2000:], flush=True)
        return 1
    print(f"Development branch pushed: {branch}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(execute(os.environ.get("DEV_INSTRUCTION", "").strip()[:worker.MAX_INSTRUCTION_LENGTH]))
