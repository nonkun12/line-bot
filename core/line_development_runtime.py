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
from .self_improvement_policy import SelfImprovementDecision, assess_self_improvement
from .self_improvement_cycle import SelfImprovementCycleResult, run_self_improvement_cycle
from .execution_safety import GitWorktreeSafetyGate
from .multi_agent import AgentResult, AgentRole, AgentTask
from .idea_ai import IdeaAgent
from .idea_handoff import IdeaAcceptance, handoff_idea
from .immediate_stop import ImmediateStop, ImmediateStopController, StopReason
from .quality_runtime import QualityRuntime
from scripts import line_development_worker_v2 as worker


@dataclass
class DevelopmentState:
    client: object
    instruction: str
    autonomous_task_id: str = ""
    chosen: str | None = None
    plan: dict | None = None
    touched: list[str] | None = None
    test_output: str = ""
    tests_passed: bool = False
    baseline_status: str = ""


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




def _is_deterministic_autonomous_task(task_id: str, chosen: str | None) -> bool:
    if not task_id or not chosen:
        return False
    return (
        (task_id in {"hand-sign-uhip-contract-test", "hand-sign-uhip-contract-negative-confidence"} and chosen == "uhip/tests/test_schema_contracts.py")
        or (task_id in {"router-regression-whitespace", "router-regression-fullwidth-market"} and chosen == "tests/test_management_router.py")
    )


def _deterministic_autonomous_test_plan(chosen: str, task_id: str | None = None) -> tuple[dict | None, str | None]:
    """Return bounded, deterministic plans for explicit queued regression-test tasks.

    Enforces size limits (old <= 1200, new <= 1800) and strict anchor uniqueness
    (text.count(anchor) == 1) at generation time to fail-closed immediately without
    invoking non-deterministic LLM plan repair.
    """
    task_id = str(task_id or os.environ.get("AUTONOMOUS_TASK_ID", "")).strip()
    if not task_id:
        return None, None

    if task_id == "hand-sign-uhip-contract-test" and chosen == "uhip/tests/test_schema_contracts.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_universal_event_accepts_hand_event_with_recognition_failure"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None

        anchor = "    with pytest.raises(jsonschema.ValidationError):\n        validate(adapter, ADAPTER_SCHEMA)\n"
        count = text.count(anchor)
        if count != 1:
            return None, f"anchor_count_{chosen}:{count}"

        addition = (
            "\n\ndef test_universal_event_accepts_hand_event_with_recognition_failure():\n"
            "    event = {\n"
            '        "schema_version": "0.3",\n'
            '        "event_id": "0192f0f8-7d4a-7c1b-9d4e-7d9d3c7c9f13",\n'
            '        "session_id": "session-1",\n'
            '        "device_id": "device-1",\n'
            '        "seq": 2,\n'
            '        "t_mono_ns": 200,\n'
            '        "t_wall": "2026-09-28T01:00:01Z",\n'
            '        "source": {\n'
            '            "device_kind": "mac",\n'
            '            "sensor": "camera",\n'
            '            "engine": "mediapipe",\n'
            '            "engine_version": "0.1",\n'
            '            "model_sha256": "a" * 64,\n'
            "        },\n"
            '        "modality": "hand",\n'
            '        "payload": {\n'
            '            "gesture": "thumb_up",\n'
            '            "phase": "end",\n'
            '            "value": None,\n'
            '            "hand": {\n'
            '                "label": "right",\n'
            '                "track_id": 3,\n'
            '                "mirrored": True,\n'
            "            },\n"
            '            "confidence": {\n'
            '                "raw": 0.99,\n'
            '                "calibrated": 0.97,\n'
            "            },\n"
            '            "stability": {\n'
            '                "frames": 8,\n'
            '                "duration_ms": 160,\n'
            "            },\n"
            "        },\n"
            '        "gate": {\n'
            '            "recognition_passed": False,\n'
            '            "rule_version": "phase0-1",\n'
            "        },\n"
            '        "ttl_ms": 500,\n'
            "    }\n"
            "    validate(event, EVENT_SCHEMA)\n"
        )
        new = anchor + addition
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"

        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "hand-sign-uhip-contract-negative-confidence" and chosen == "uhip/tests/test_schema_contracts.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_universal_event_accepts_zero_confidence_hand_event"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None

        anchor = 'def test_adapter_schema_rejects_unknown_risk():\n'
        count = text.count(anchor)
        if count != 1:
            return None, f"anchor_count_{chosen}:{count}"

        before = text.split(anchor, 1)[0]
        if before and not before.endswith("\n\n"):
            return None, "deterministic_plan_invalid:anchor_not_standalone_def"

        addition = (
            "\n\ndef test_universal_event_accepts_zero_confidence_hand_event():\n"
            "    event = {\n"
            '        "schema_version": "0.3",\n'
            '        "event_id": "0192f0f8-7d4a-7c1b-9d4e-7d9d3c7c9f14",\n'
            '        "session_id": "session-1",\n'
            '        "device_id": "device-1",\n'
            '        "seq": 3,\n'
            '        "t_mono_ns": 300,\n'
            '        "source": {\n'
            '            "device_kind": "mac",\n'
            '            "sensor": "camera",\n'
            '            "engine": "mediapipe",\n'
            '            "engine_version": "0.1",\n'
            '            "model_sha256": "a" * 64,\n'
            "        },\n"
            '        "modality": "hand",\n'
            '        "payload": {\n'
            '            "gesture": "thumb_up",\n'
            '            "phase": "end",\n'
            '            "value": None,\n'
            '            "hand": {\n'
            '                "label": "right",\n'
            '                "track_id": 4,\n'
            '                "mirrored": True,\n'
            "            },\n"
            '            "confidence": {\n'
            '                "raw": 0.0,\n'
            '                "calibrated": 0.0,\n'
            "            },\n"
            "        },\n"
            '        "gate": {\n'
            '            "recognition_passed": False,\n'
            '            "rule_version": "phase0-1",\n'
            "        },\n"
            '        "ttl_ms": 500,\n'
            "    }\n"
            "    validate(event, EVENT_SCHEMA)\n"
        )
        new_test = addition.lstrip("\n")
        new = new_test + "\n\n" + anchor
        candidate = text.replace(anchor, new, 1)
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"

        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "router-regression-whitespace" and chosen == "tests/test_management_router.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_routes_jobs_request_with_surrounding_whitespace"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None

        anchor = '    assert decision.metadata["request_metadata"]["source"] == "parallel-dev-test"\n'
        count = text.count(anchor)
        if count != 1:
            return None, f"anchor_count_{chosen}:{count}"

        addition = (
            "\n\ndef test_routes_jobs_request_with_surrounding_whitespace() -> None:\n"
            '    assert route(ManagementRequest("u", "  求人を探して  ")).specialist is Specialist.JOBS\n'
        )
        new = anchor + addition
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"

        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "router-regression-fullwidth-market" and chosen == "tests/test_management_router.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_routes_fullwidth_market_request_after_normalization"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None

        anchor = '    assert decision.metadata["request_metadata"]["source"] == "parallel-dev-test"\n'
        if "test_routes_jobs_request_with_surrounding_whitespace" in text:
            anchor = '    assert route(ManagementRequest("u", "  求人を探して  ")).specialist is Specialist.JOBS\n'

        count = text.count(anchor)
        if count != 1:
            return None, f"anchor_count_{chosen}:{count}"

        addition = (
            "\n\ndef test_routes_fullwidth_market_request_after_normalization() -> None:\n"
            '    assert route(ManagementRequest("u", "ＮＹダウを教えて")).specialist is Specialist.MARKET\n'
        )
        new = anchor + addition
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"

        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    return None, None


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
                task_id = self.state.autonomous_task_id.strip()
                if not task_id:
                    task_id = os.environ.get("AUTONOMOUS_TASK_ID", "").strip()
                # Exact instruction fallback is bounded to the known queued task and target.
                if (
                    not task_id
                    and self.state.chosen == "uhip/tests/test_schema_contracts.py"
                    and "confidence=0.0" in self.state.instruction
                    and "recognition_passed=false" in self.state.instruction
                ):
                    task_id = "hand-sign-uhip-contract-negative-confidence"
                deterministic_plan, deterministic_err = _deterministic_autonomous_test_plan(
                    self.state.chosen,
                    task_id,
                )
                if deterministic_err:
                    return AgentResult(task.task_id, False, f"deterministic plan generation failed: {deterministic_err}")
                if deterministic_plan is not None:
                    ok, detail = worker.validate_plan(deterministic_plan, self.state.chosen)
                    if not ok:
                        return AgentResult(task.task_id, False, f"deterministic plan rejected: {detail}")
                    if detail == "no_change":
                        self.state.plan = deterministic_plan
                        self.state.touched = []
                        return AgentResult(task.task_id, True, "no safe change required")
                    applied, detail, touched = worker.apply_plan(deterministic_plan)
                    if not applied:
                        worker.restore(touched)
                        return AgentResult(task.task_id, False, f"apply failed: {detail}")
                    self.state.plan = deterministic_plan
                    self.state.touched = touched
                    return AgentResult(task.task_id, True, "guarded change applied", frozenset(touched))

                explicit_comment_plan = _explicit_comment_plan(self.state.instruction, self.state.chosen)
                comment_plan = None if explicit_comment_plan is not None else worker.build_comment_test_plan(self.state.instruction, self.state.chosen)
                context = worker.context_for(self.state.chosen)
                plan = (
                    explicit_comment_plan
                    if explicit_comment_plan is not None
                    else comment_plan
                    if comment_plan is not None
                    else worker.build_plan(
                        self.state.client,
                        self.state.instruction,
                        self.state.chosen,
                        context,
                    )
                )
                plan, ok, detail = worker.validate_plan_with_bounded_repairs(
                    self.state.client,
                    self.state.instruction,
                    self.state.chosen,
                    plan,
                    context,
                )
                if not ok:
                    return AgentResult(task.task_id, False, f"implementation plan rejected: {detail}")
                if detail == "no_change":
                    self.state.plan = plan; self.state.touched = []
                    return AgentResult(task.task_id, True, "no safe change required")
                plan, applied, detail, touched = worker.apply_plan_with_bounded_anchor_repair(
                    self.state.client,
                    self.state.instruction,
                    self.state.chosen,
                    plan,
                    context,
                )
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
                task_id = os.environ.get("AUTONOMOUS_TASK_ID", "").strip()
                if _is_deterministic_autonomous_task(task_id, self.state.chosen):
                    return AgentResult(task.task_id, False, "deterministic test failure; schema and test must not be mutated by LLM")
                if _is_deterministic_comment_request(self.state.instruction, self.state.chosen):
                    return AgentResult(task.task_id, True, "deterministic debug retry; no LLM JSON parsing")
                worker.restore(self.state.touched or [])
                failure_context = task.instruction
                if self.state.test_output:
                    failure_context = f"{failure_context}\nPrevious test output:\n{self.state.test_output[-4000:]}"
                context = worker.context_for(self.state.chosen)
                plan = worker.build_plan(
                    self.state.client,
                    self.state.instruction,
                    self.state.chosen,
                    context,
                    failure_context,
                )
                plan, ok, detail = worker.validate_plan_with_bounded_repairs(
                    self.state.client,
                    self.state.instruction,
                    self.state.chosen,
                    plan,
                    context,
                )
                if not ok or detail == "no_change":
                    return AgentResult(task.task_id, False, f"debug plan rejected: {detail}")
                plan, applied, detail, touched = worker.apply_plan_with_bounded_anchor_repair(
                    self.state.client,
                    self.state.instruction,
                    self.state.chosen,
                    plan,
                    context,
                )
                if not applied:
                    worker.restore(touched)
                    return AgentResult(task.task_id, False, f"debug apply failed: {detail}")
                self.state.plan = plan; self.state.touched = touched
                return AgentResult(task.task_id, True, "debug fix applied", frozenset(touched))
            if task.role is AgentRole.REFACTORER:
                task_id = os.environ.get("AUTONOMOUS_TASK_ID", "").strip()
                if _is_deterministic_autonomous_task(task_id, self.state.chosen):
                    return AgentResult(task.task_id, True, "no refactor needed for deterministic test task")
                if _is_deterministic_comment_request(self.state.instruction, self.state.chosen):
                    return AgentResult(task.task_id, True, "no refactor needed for deterministic comment change")
                plan = worker.build_plan(self.state.client, f"Refactor the current implementation for clarity, maintainability, and duplication reduction. Preserve behavior and satisfy the original request. Original request: {self.state.instruction}", self.state.chosen, worker.context_for(self.state.chosen), self.state.test_output)
                plan, ok, detail = worker.validate_plan_with_bounded_repairs(
                    self.state.client,
                    self.state.instruction,
                    self.state.chosen,
                    plan,
                    worker.context_for(self.state.chosen),
                )
                if not ok:
                    return AgentResult(task.task_id, False, f"refactor plan rejected: {detail}")
                if detail == "no_change":
                    return AgentResult(task.task_id, True, "no refactor change required")
                plan, applied, detail, touched = worker.apply_plan_with_bounded_anchor_repair(
                    self.state.client,
                    self.state.instruction,
                    self.state.chosen,
                    plan,
                    worker.context_for(self.state.chosen),
                )
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
                plan, ok, detail = worker.validate_plan_with_bounded_repairs(
                    self.state.client,
                    self.state.instruction,
                    self.state.chosen,
                    plan,
                    worker.context_for(self.state.chosen),
                )
                if not ok or detail == "no_change":
                    return AgentResult(task.task_id, False, f"repair plan rejected: {detail}")
                worker.restore(self.state.touched or [])
                plan, applied, detail, touched = worker.apply_plan_with_bounded_anchor_repair(
                    self.state.client,
                    self.state.instruction,
                    self.state.chosen,
                    plan,
                    worker.context_for(self.state.chosen),
                )
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


def _write_development_audit_to_google_sheets(*, instruction: str, status: str, target_path: str | None, branch: str | None, exit_detail: str, base_sha: str | None, produced_sha: str | None) -> None:
    """Best-effort append of autonomous-development audit data to Google Sheets."""
    if os.environ.get("GOOGLE_SHEETS_AUDIT_ENABLED", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return
    try:
        from .google_sheets_writer import GoogleSheetsWriter
        writer = GoogleSheetsWriter.from_environment()
        if writer is None:
            print("[GOOGLE-SHEETS] audit skipped: configuration incomplete", flush=True)
            return
        writer.append_development_result(instruction=instruction, status=status, target_path=target_path, branch=branch, detail=exit_detail, base_sha=base_sha, produced_sha=produced_sha)
        print("[GOOGLE-SHEETS] audit appended", flush=True)
    except Exception as exc:
        print(f"[GOOGLE-SHEETS] audit write failed (non-blocking): {type(exc).__name__}: {exc}", flush=True)



def _prepare_idea_stage(instruction: str) -> tuple[str, str | None, str | None]:
    """Optionally run the bounded IDEA stage before implementation.
    
    IDEA_MODE is opt-in. Without explicit acceptance, the loop stops before
    any implementation task is created. This preserves human-on-the-loop.
    """
    if os.environ.get("IDEA_MODE", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return instruction, None, None

    ideas = IdeaAgent().propose(instruction, limit=5)
    requested_id = os.environ.get("IDEA_ACCEPTED_ID", "").strip()
    accepted = next((idea for idea in ideas if idea.idea_id == requested_id), None)
    if accepted is None:
        print(
            "[IDEA] proposals generated; no explicit acceptance. "
            "Implementation blocked closed.",
            flush=True,
        )
        for idea in ideas:
            print(f"[IDEA] {idea.idea_id}: {idea.title}", flush=True)
        return instruction, None, "IDEA acceptance required"

    acceptance_reason = os.environ.get(
        "IDEA_ACCEPTANCE_REASON",
        "explicit human-on-the-loop acceptance",
    ).strip()[:500]
    handoff = handoff_idea(
        accepted,
        IdeaAcceptance(accepted=True, reason=acceptance_reason),
    )
    if handoff is None:
        return instruction, None, "IDEA handoff rejected"

    print(
        f"[IDEA] accepted={accepted.idea_id}; handoff={handoff.task_id}; "
        "implementation remains behind normal quality/safety gates",
        flush=True,
    )
    return handoff.instruction, handoff.task_id, None

def execute(instruction: str) -> int:
    """Run one real guarded development request through the quality pipeline."""
    stop_controller = ImmediateStopController()
    try:
        stop_controller.assert_can_execute()
    except ImmediateStop as exc:
        print(f"IMMEDIATE STOP: {exc}", flush=True)
        _write_development_audit_to_google_sheets(instruction=instruction, status="STOP", target_path=None, branch=None, exit_detail=str(exc), base_sha=None, produced_sha=None)
        return 1
    instruction, idea_task_id, idea_block_reason = _prepare_idea_stage(instruction)
    if idea_block_reason is not None:
        _write_development_audit_to_google_sheets(
            instruction=instruction,
            status="BLOCKED",
            target_path=None,
            branch=None,
            exit_detail=idea_block_reason,
            base_sha=None,
            produced_sha=None,
        )
        return 1
    if idea_task_id:
        os.environ["AUTONOMOUS_TASK_ID"] = idea_task_id
    client = worker.Groq(api_key=os.environ["GROQ_API_KEY"])
    state = DevelopmentState(
        client=client,
        instruction=instruction,
        autonomous_task_id=os.environ.get("AUTONOMOUS_TASK_ID", "").strip(),
    )
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
    try:
        stop_controller.assert_can_execute()
        manager_result = executor.execute(tasks[0])
    except ImmediateStop as exc:
        print(f"IMMEDIATE STOP: {exc}", flush=True)
        _write_development_audit_to_google_sheets(instruction=instruction, status="STOP", target_path=None, branch=None, exit_detail=str(exc), base_sha=None, produced_sha=None)
        return 1
    if not manager_result.success:
        print(f"Manager selection failed: {manager_result.summary}", flush=True)
        _write_development_audit_to_google_sheets(instruction=instruction, status="BLOCKED", target_path=None, branch=None, exit_detail=manager_result.summary, base_sha=None, produced_sha=None)
        return 1
    if state.chosen is None:
        print("Manager produced no target.", flush=True)
        _write_development_audit_to_google_sheets(instruction=instruction, status="BLOCKED", target_path=None, branch=None, exit_detail="manager produced no target", base_sha=None, produced_sha=None)
        return 1
    if os.environ.get("SELF_IMPROVEMENT_POLICY_ENFORCED", "").strip().lower() in {"1", "true", "yes", "on"}:
        assessment = assess_self_improvement((state.chosen,))
        if assessment.decision is not SelfImprovementDecision.AUTONOMOUS_REVIEW:
            detail = "; ".join(assessment.reasons)
            print(f"Self-improvement policy blocked autonomous target {state.chosen}: {detail}", flush=True)
            _write_development_audit_to_google_sheets(
                instruction=instruction,
                status="BLOCKED",
                target_path=state.chosen,
                branch=None,
                exit_detail=detail,
                base_sha=None,
                produced_sha=None,
            )
            return 1
    baseline = worker.run(["git", "status", "--porcelain=v1", "--untracked-files=all"])
    if baseline.returncode != 0:
        print(f"Baseline status failed: {baseline.stderr[-2000:]}", flush=True)
        return 1
    state.baseline_status = baseline.stdout
    if baseline.stdout.strip():
        print("Worktree is not clean before autonomous execution; refusing to proceed.", flush=True)
        _write_development_audit_to_google_sheets(instruction=instruction, status="BLOCKED", target_path=state.chosen, branch=None, exit_detail="worktree is not clean", base_sha=None, produced_sha=None)
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
        immediate_stop_controller=stop_controller,
    )
    try:
        report = runtime.run(tasks[1:])
    except Exception as exc:
        _rollback_to_clean_baseline(baseline_sha)
        detail = f"{type(exc).__name__}: {exc}"
        print(f"Multi-agent development failed closed: {detail}", flush=True)
        stopped = stop_controller.is_stopped()
        _write_development_audit_to_google_sheets(instruction=instruction, status="STOP" if stopped else "FAIL", target_path=state.chosen, branch=None, exit_detail=detail, base_sha=baseline_sha, produced_sha=None)
        return 1
    print(f"[manager] {tasks[0].task_id}: {manager_result.summary[-1500:]}", flush=True)
    for item in report.completed:
        print(f"[{item.task.role.value}] {item.task.task_id}: {item.result.summary[-1500:]}", flush=True)
    improvement_result = observe_self_improvement(report, state.chosen)
    if not report.success or not report.integration_ready:
        _rollback_to_clean_baseline(baseline_sha)
        detail = report.error or report.failed_task_id or "quality runtime failed"
        print(f"Multi-agent development failed: {detail}", flush=True)
        stopped = stop_controller.is_stopped()
        _write_development_audit_to_google_sheets(instruction=instruction, status="STOP" if stopped else "FAIL", target_path=state.chosen, branch=None, exit_detail=detail, base_sha=baseline_sha, produced_sha=None)
        return 1
    touched = state.touched or []
    if not touched:
        _rollback_to_clean_baseline(baseline_sha)
        print("Multi-agent development produced no file change; treating as a safe no-op.", flush=True)
        _write_development_audit_to_google_sheets(
            instruction=instruction,
            status="NO_CHANGE",
            target_path=state.chosen,
            branch=None,
            exit_detail="no file change",
            base_sha=baseline_sha,
            produced_sha=baseline_sha,
        )
        return 0
    try:
        stop_controller.assert_can_execute()
    except ImmediateStop as exc:
        _rollback_to_clean_baseline(baseline_sha)
        _write_development_audit_to_google_sheets(instruction=instruction, status="STOP", target_path=state.chosen, branch=None, exit_detail=str(exc), base_sha=baseline_sha, produced_sha=None)
        return 1
    branch = f"line-dev/{os.environ.get('GITHUB_RUN_ID', 'manual')}"
    identity = ["-c", "user.name=github-actions[bot]", "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com"]
    add = worker.run(["git", "add", "--", *touched])
    if add.returncode != 0:
        worker.restore(touched); print(add.stderr[-2000:], flush=True); return 1
    status = worker.run(["git", "status", "--short"])
    if status.returncode != 0 or not status.stdout.strip():
        worker.restore(touched); print("No changes to commit.", flush=True); return 1
    try:
        stop_controller.assert_can_execute()
    except ImmediateStop as exc:
        _rollback_to_clean_baseline(baseline_sha)
        _write_development_audit_to_google_sheets(instruction=instruction, status="STOP", target_path=state.chosen, branch=None, exit_detail=str(exc), base_sha=baseline_sha, produced_sha=None)
        return 1
    commit = worker.run(["git", *identity, "commit", "-m", "feat: LINE development request"])
    if commit.returncode != 0:
        worker.restore(touched); print(commit.stderr[-2000:], flush=True); return 1
    checkout = worker.run(["git", "checkout", "-B", branch])
    if checkout.returncode != 0:
        print(checkout.stderr[-2000:], flush=True); return 1
    try:
        stop_controller.assert_can_execute()
    except ImmediateStop as exc:
        _rollback_to_clean_baseline(baseline_sha)
        _write_development_audit_to_google_sheets(instruction=instruction, status="STOP", target_path=state.chosen, branch=branch, exit_detail=str(exc), base_sha=baseline_sha, produced_sha=None)
        return 1
    push = worker.run(["git", "push", "--set-upstream", "origin", branch])
    if push.returncode != 0:
        print(push.stderr[-2000:], flush=True); return 1
    produced = worker.run(["git", "rev-parse", "HEAD"])
    produced_sha = produced.stdout.strip() if produced.returncode == 0 else None
    _write_development_audit_to_google_sheets(instruction=instruction, status="PASS", target_path=state.chosen, branch=branch, exit_detail="development branch pushed", base_sha=baseline_sha, produced_sha=produced_sha)
    print(f"Development branch pushed: {branch}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(execute(os.environ.get("DEV_INSTRUCTION", "").strip()[:worker.MAX_INSTRUCTION_LENGTH]))
