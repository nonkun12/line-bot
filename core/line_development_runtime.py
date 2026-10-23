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


def _push_development_branch(branch: str) -> tuple[bool, str]:
    """Push normally, or defer publishing to the authenticated GitHub Actions step."""
    if os.environ.get("AUTONOMOUS_PUBLISH_VIA_WORKFLOW", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True, "deferred_to_authenticated_workflow_publisher"
    push = worker.run(["git", "push", "--set-upstream", "origin", branch])
    if push.returncode != 0:
        return False, push.stderr[-2000:] or "git push failed"
    return True, "development branch pushed"


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
    *,
    allow_external_ai: bool = True,
) -> SelfImprovementCycleResult | None:
    """Feed eligible development reports into bounded self-improvement.

    Deterministic queue tasks disable external AI but still record bounded local
    signals and deterministic analysis. Do not infer provider policy from the
    ambient task ID: unrelated callers can run in the same environment.
    """
    try:
        feedback_engine = SelfImprovementEngine()
        creator_critic = (
            build_creator_critic_loop(max_iterations=1)
            if allow_external_ai and _self_improvement_creator_critic_enabled()
            else None
        )
        if not allow_external_ai:
            print(
                "[SELF-IMPROVEMENT] external AI disabled; local observation only",
                flush=True,
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
        reviewer_enabled = allow_external_ai and _self_improvement_creator_critic_enabled()
        decisions = getattr(result, "control_tower_decisions", ())
        approved = len(result.approved_proposals)
        review_errors = sum(1 for decision in decisions if decision.review_error is not None)
        unreviewed = sum(1 for decision in decisions if not decision.duel and decision.review_error is None)
        reviewer_mode = "creator_critic" if reviewer_enabled else (
            "local_only_external_ai_disabled" if not allow_external_ai else "disabled_by_config"
        )
        print(
            "[CONTROL-TOWER] "
            f"status=observed reviewer={reviewer_mode} "
            f"signals={len(result.new_signals)} "
            f"patterns={len(result.analysis.recurring_patterns)} "
            f"proposals={len(result.proposals)} "
            f"reviewed={sum(1 for decision in decisions if decision.duel)} "
            f"approved={approved} unreviewed={unreviewed} review_errors={review_errors}",
            flush=True,
        )
        return result
    except Exception as exc:
        # Improvement observation must never turn a validated development result
        # into an unrelated deployment failure.
        print(
            f"[CONTROL-TOWER] status=observation_error error_class={type(exc).__name__}",
            flush=True,
        )
        return None




_DETERMINISTIC_AUTONOMOUS_TASK_TARGETS = {
    "hand-sign-uhip-contract-phase-start": "uhip/tests/test_schema_contracts.py",
    "hand-sign-uhip-contract-left-hand": "uhip/tests/test_schema_contracts.py",
    "router-regression-jobs-market-metadata": "tests/test_management_router.py",
    "router-regression-english-casefold": "tests/test_management_router.py",
    "hand-sign-uhip-contract-test": "uhip/tests/test_schema_contracts.py",
    "hand-sign-uhip-contract-negative-confidence": "uhip/tests/test_schema_contracts.py",
    "hand-sign-uhip-contract-iphone-camera": "uhip/tests/test_schema_contracts.py",
    "hand-sign-uhip-contract-unknown-hand-label": "uhip/tests/test_schema_contracts.py",
    "uhip-confidence-boundary-acceptance": "uhip/tests/test_schema_contracts.py",
    "uhip-confidence-out-of-range-rejection": "uhip/tests/test_schema_contracts.py",
    "router-regression-whitespace": "tests/test_management_router.py",
    "router-regression-fullwidth-market": "tests/test_management_router.py",
    "router-regression-casefold-english": "tests/test_management_router.py",
    "router-regression-mixed-specialists": "tests/test_management_router.py",
    "router-regression-stock-jobs-priority": "tests/test_management_router.py",
    "router-regression-market-channel-metadata": "tests/test_management_router.py",
    "macos-readiness-audit-no-secret-leak": "tests/test_macos_kanban_obsidian_readiness.py",
    "router-regression-general-request-metadata": "tests/test_management_router.py",
    "router-regression-general-request-metadata-refresh-20261015": "tests/test_management_router.py",
    "recovery-ai-loop-adapter-durable-state-readback": "tests/test_recovery_ai_loop_adapter.py",
    "control-tower-recovery-evidence-identity-mismatch": "tests/test_control_tower_orchestrator.py",
    "control-tower-run-identity-invalid-sha-regression": "tests/test_control_tower_orchestrator.py",
    "control-tower-run-identity-invalid-sha-regression-v2": "tests/test_control_tower_orchestrator.py",
    "english-core-image-rotation-user-isolation": "tests/test_english_learning.py",
    "english-core-image-rotation-user-isolation-v2": "tests/test_english_learning.py",
    "english-core-image-unknown-word-safe-fallback": "tests/test_english_learning.py",
    "recovery-ai-state-isolation": "tests/test_recovery_ai.py",
    "ai-speaker-empty-transcript-no-brain-call": "tests/test_ai_speaker.py",
    "distributed-loop-queue-progress-empty-queue-regression": "tests/test_distributed_loop_queue_progress.py",
    "distributed-loop-queue-progress-empty-queue-regression-v2": "tests/test_distributed_loop_queue_progress.py",
    "loop-deterministic-nochange-focused-test": "tests/test_line_development_worker_v2.py",
    "self-improvement-history-malformed-jsonl-regression": "tests/test_self_improvement_state.py",
    "refill-rejects-malformed-completed-state": "tests/test_autonomous_task_refill.py",
    "refill-rejects-malformed-recovery-task-entry": "tests/test_autonomous_task_refill.py",
    "refill-rejects-non-ascii-task-id": "tests/test_autonomous_task_refill.py",
    "refill-all-catalog-candidates-ineligible-regression": "tests/test_autonomous_task_refill.py",
    "loop-refill-empty-catalog-next-safe-test-20261023": "tests/test_autonomous_task_refill.py",
    "refill-rejects-boolean-catalog-addition-cap": "tests/test_autonomous_task_refill.py",
    "refill-rejects-nonobject-recovery-task-map": "tests/test_autonomous_task_refill.py",
}

def _is_deterministic_autonomous_task(task_id: str, chosen: str | None) -> bool:
    if not task_id or not chosen:
        return False
    return _DETERMINISTIC_AUTONOMOUS_TASK_TARGETS.get(task_id) == chosen


def _autonomous_task_id_for_state(state: DevelopmentState) -> str:
    """Use ambient task identity only when it matches the selected target.
    
    Unit/runtime callers may share AUTONOMOUS_TASK_ID across isolated executor
    tests. Never turn an unrelated selected file into a deterministic-target
    mismatch merely because that ambient variable is present.
    """
    task_id = state.autonomous_task_id.strip()
    if task_id:
        return task_id
    ambient = os.environ.get("AUTONOMOUS_TASK_ID", "").strip()
    if not ambient or not state.chosen:
        return ""
    return ambient if _DETERMINISTIC_AUTONOMOUS_TASK_TARGETS.get(ambient) == state.chosen else ""


def _deterministic_autonomous_test_plan(chosen: str, task_id: str | None = None) -> tuple[dict | None, str | None]:
    """Return bounded, deterministic plans for explicit queued regression-test tasks.

    Enforces size limits (old <= 1200, new <= 1800) and strict anchor uniqueness
    (text.count(anchor) == 1) at generation time to fail-closed immediately without
    invoking non-deterministic LLM plan repair.
    """
    # Deterministic task identity must come from the guarded executor state.
    # Never consult ambient AUTONOMOUS_TASK_ID here: it can leak across
    # isolated unit tests and turn unrelated targets into false mismatches.
    task_id = str(task_id or "").strip()
    if not task_id:
        return None, None

    # Known autonomous test tasks are deterministic and fail closed if the
    # manager selects any target other than the declared target.
    expected_target = _DETERMINISTIC_AUTONOMOUS_TASK_TARGETS.get(task_id)
    if expected_target is not None and chosen != expected_target:
        return None, "deterministic_target_mismatch"

    control_tower_regressions = {
        "control-tower-recovery-evidence-identity-mismatch": "test_recovery_evidence_identity_mismatch_fails_closed",
        "control-tower-run-identity-invalid-sha-regression": "test_invalid_sha_format_fails_closed",
        "control-tower-run-identity-invalid-sha-regression-v2": "test_invalid_sha_format_fails_closed",
    }
    if task_id in control_tower_regressions and chosen == "tests/test_control_tower_orchestrator.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        required_test = control_tower_regressions[task_id]
        if f"def {required_test}(" not in text:
            return None, f"required_regression_test_missing:{required_test}"
        return {"no_change": True, "source": "deterministic_autonomous_task"}, None

    english_core_image_regressions = {
        "english-core-image-rotation-user-isolation": "test_vocabulary_rotation_is_independent_per_user",
        "english-core-image-rotation-user-isolation-v2": "test_vocabulary_rotation_is_independent_per_user",
        "english-core-image-unknown-word-safe-fallback": "test_unknown_core_image_word_fails_closed_without_guessing",
    }
    if task_id in english_core_image_regressions and chosen == "tests/test_english_learning.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        required_test = english_core_image_regressions[task_id]
        if f"def {required_test}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None
        if task_id != "english-core-image-unknown-word-safe-fallback":
            return None, f"required_regression_test_missing:{required_test}"
        anchor = "def test_core_image_command_is_classified_as_english_learning_intent():"
        if text.count(anchor) != 1:
            return None, f"anchor_count_{chosen}:{text.count(anchor)}"
        newline = chr(10)
        addition = newline.join([
            "def test_unknown_core_image_word_fails_closed_without_guessing():",
            "    from agents.english.core_image import handle_core_image_command",
            "",
            '    response = handle_core_image_command("florpt コアイメージ")',
            '    assert response is not None',
            '    assert "無料ローカル辞書に確かな解説がありません" in response',
            '    assert "語源や語根を推測で断定しない" in response',
            '    assert "ブランド" not in response',
            "",
            "",
        ]) + newline
        new = addition + anchor
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"
        candidate = text.replace(anchor, new, 1)
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "refill-rejects-malformed-completed-state" and chosen == "tests/test_autonomous_task_refill.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_refill_fails_closed_on_non_string_completed_state"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None
        anchor = "def test_refill_fails_closed_when_recovery_ai_state_is_missing(tmp_path: Path):\n"
        if text.count(anchor) != 1:
            return None, f"anchor_count_{chosen}:{text.count(anchor)}"
        newline = chr(10)
        addition = newline.join([
            "def test_refill_fails_closed_on_non_string_completed_state(tmp_path: Path):",
            '    queue, catalog, completed = _inputs(tmp_path, candidates=[_task("task-ready-one")])',
            '    state = _write(tmp_path / "state.json", {"version": 1, "completed": ["task-done", 7], "recovery_ai": {"schema_version": 1, "tasks": {}, "checkpoint": None}})',
            '    output = tmp_path / "runtime.json"',
            '    with pytest.raises(ValueError, match="completed state must be a string list"):',
            "        build_queue(queue, catalog, state, output)",
            "    assert not output.exists()",
            "",
            "",
        ]) + newline
        new = addition + anchor
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"
        candidate = text.replace(anchor, new, 1)
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "refill-rejects-malformed-recovery-task-entry" and chosen == "tests/test_autonomous_task_refill.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_refill_fails_closed_on_malformed_recovery_ai_task_entry"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None
        anchor = "def test_refill_fails_closed_on_invalid_recovery_ai_held_flag(tmp_path: Path):\n"
        if text.count(anchor) != 1:
            return None, f"anchor_count_{chosen}:{text.count(anchor)}"
        newline = chr(10)
        addition = newline.join([
            "def test_refill_fails_closed_on_malformed_recovery_ai_task_entry(tmp_path: Path):",
            '    queue, catalog, completed = _inputs(tmp_path, candidates=[_task("task-ready-one")])',
            '    state = _write(tmp_path / "state.json", {',
            '        "version": 1,',
            '        "completed": [],',
            '        "recovery_ai": {',
            '            "schema_version": 1,',
            '            "tasks": {"task-bad": "not-an-object"},',
            '            "checkpoint": None,',
            '        },',
            '    })',
            '    output = tmp_path / "runtime.json"',
            '    with pytest.raises(ValueError, match="invalid Recovery AI task state"):',
            '        build_queue(queue, catalog, state, output)',
            '    assert not output.exists()',
            "",
            "",
        ]) + newline
        new = addition + anchor
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"
        candidate = text.replace(anchor, new, 1)
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "refill-rejects-nonobject-recovery-task-map" and chosen == "tests/test_autonomous_task_refill.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_refill_fails_closed_on_nonobject_recovery_task_map"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None
        anchor = "def test_refill_fails_closed_on_invalid_recovery_ai_schema(tmp_path: Path):"
        if text.count(anchor) != 1:
            return None, f"anchor_count_{chosen}:{text.count(anchor)}"
        newline = chr(10)
        addition = newline.join([
            "def test_refill_fails_closed_on_nonobject_recovery_task_map(tmp_path: Path):",
            "    queue, catalog, completed = _inputs(tmp_path, candidates=[_task(\"task-ready-one\")])",
            "    state = _write(tmp_path / \"state.json\", {",
            "        \"version\": 1,",
            "        \"completed\": [],",
            "        \"recovery_ai\": {",
            "            \"schema_version\": 1,",
            "            \"tasks\": [],",
            "            \"checkpoint\": None,",
            "        },",
            "    })",
            "    output = tmp_path / \"runtime.json\"",
            "    with pytest.raises(ValueError, match=\"Recovery AI state is invalid\"):",
            "        build_queue(queue, catalog, state, output)",
            "    assert not output.exists()"
            "",
            "",
        ]) + newline
        new = addition + anchor
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"
        candidate = text.replace(anchor, new, 1)
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "refill-rejects-boolean-catalog-addition-cap" and chosen == "tests/test_autonomous_task_refill.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_refill_rejects_boolean_catalog_addition_cap"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None
        anchor = "def test_refill_rejects_duplicate_catalog_ids(tmp_path: Path):"
        if text.count(anchor) != 1:
            return None, f"anchor_count_{chosen}:{text.count(anchor)}"
        newline = chr(10)
        addition = newline.join([
            "def test_refill_rejects_boolean_catalog_addition_cap(tmp_path: Path):",
            "    queue, catalog, completed = _inputs(tmp_path, candidates=[_task(\"task-ready-one\")])",
            "    catalog_data = json.loads(catalog.read_text(encoding=\"utf-8\"))",
            "    catalog_data[\"max_additions_per_run\"] = True",
            "    catalog.write_text(json.dumps(catalog_data), encoding=\"utf-8\")",
            "    output = tmp_path / \"runtime.json\"",
            "    with pytest.raises(ValueError, match=\"catalog cap must be between 1 and 4\"):",
            "        build_queue(queue, catalog, completed, output)",
            "    assert not output.exists()"
            "",
            "",
        ]) + newline
        new = addition + anchor
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"
        candidate = text.replace(anchor, new, 1)
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "refill-rejects-non-ascii-task-id" and chosen == "tests/test_autonomous_task_refill.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_refill_rejects_non_ascii_task_id"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None
        anchor = "def test_refill_rejects_duplicate_existing_queue_ids(tmp_path: Path):"
        if text.count(anchor) != 1:
            return None, f"anchor_count_{chosen}:{text.count(anchor)}"
        newline = chr(10)
        addition = newline.join([
            "def test_refill_rejects_non_ascii_task_id(tmp_path: Path):",
            "    queue, catalog, completed = _inputs(tmp_path, candidates=[_task(\"タスク-a\")])",
            "    output = tmp_path / \"runtime.json\"",
            "    with pytest.raises(ValueError, match=\"invalid task ID\"):",
            "        build_queue(queue, catalog, completed, output)",
            "    assert not output.exists()"
            "",
            "",
        ]) + newline
        new = addition + anchor
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"
        candidate = text.replace(anchor, new, 1)
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "self-improvement-history-malformed-jsonl-regression" and chosen == "tests/test_self_improvement_state.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_read_jsonl_skips_malformed_rows_and_preserves_valid_order"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None
        anchor = "def test_sanitizer_discards_raw_error_text_and_unknown_fields():\n"
        if text.count(anchor) != 1:
            return None, f"anchor_count_{chosen}:{text.count(anchor)}"
        newline = chr(10)
        addition = newline.join([
            "def test_read_jsonl_skips_malformed_rows_and_preserves_valid_order(tmp_path):",
            "    from scripts.self_improvement_state import read_jsonl",
            "    history = tmp_path / \"history.jsonl\"",
            "    history.write_text(",
            "        '{\"kind\": \"success\", \"task_id\": \"task-a\"}\\n'",
            "        '{malformed json}\\n'",
            "        '{\"kind\": \"failure\", \"task_id\": \"task-b\"}\\n',",
            "        encoding=\"utf-8\",",
            "    )",
            "    assert read_jsonl(history) == [",
            "        {\"kind\": \"success\", \"task_id\": \"task-a\"},",
            "        {\"kind\": \"failure\", \"task_id\": \"task-b\"},",
            "    ]",
            "",
            "",
        ]) + newline
        new = addition + anchor
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"
        candidate = text.replace(anchor, new, 1)
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "distributed-loop-queue-progress-empty-queue-regression-v2" and chosen == "tests/test_distributed_loop_queue_progress.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_empty_runtime_queue_reports_zero_progress_for_not_run_v2"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None
        newline = chr(10)
        anchor = "def test_progress_uses_runtime_queue_and_counts_refill_tasks(tmp_path: Path):" + newline
        if text.count(anchor) != 1:
            return None, f"anchor_count_{chosen}:{text.count(anchor)}"
        addition = newline.join([
            "def test_empty_runtime_queue_reports_zero_progress_for_not_run_v2(tmp_path: Path):",
            "    queue = tmp_path / \"runtime-queue.json\"",
            "    state = tmp_path / \"state.json\"",
            "    results = tmp_path / \"results.jsonl\"",
            "    queue.write_text(json.dumps({\"tasks\": []}), encoding=\"utf-8\")",
            "    state.write_text(json.dumps({\"completed\": [\"prior-task\"]}), encoding=\"utf-8\")",
            "    results.write_text(json.dumps({\"task_id\": \"\", \"status\": \"NOT_RUN\", \"failure_reason\": \"queue_empty\"}), encoding=\"utf-8\")",
            "    assert calculate_progress(queue, state, results) == {\"queue_total\": 0, \"queue_completed\": 0}",
            "",
            "",
        ]) + newline
        new = addition + anchor
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"
        candidate = text.replace(anchor, new, 1)
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "loop-deterministic-nochange-focused-test" and chosen == "tests/test_line_development_worker_v2.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        test_name = "def test_run_tests_can_verify_only_allowlisted_target_for_no_change("
        if test_name in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None
        anchor = "def test_worker_entrypoint_is_executable():\n"
        if text.count(anchor) != 1:
            return None, f"anchor_count_{chosen}:{text.count(anchor)}"
        test = (
            "def test_run_tests_can_verify_only_allowlisted_target_for_no_change(monkeypatch, tmp_path):\n"
            "    calls = []\n\n"
            "    def fake_run(cmd, timeout=900, input_text=None):\n"
            "        calls.append(cmd)\n"
            "        return subprocess.CompletedProcess(cmd, 0, stdout='1 passed', stderr='')\n\n"
            "    monkeypatch.setattr(worker, 'ROOT', tmp_path)\n"
            "    monkeypatch.setattr(worker, 'run', fake_run)\n"
            "    passed, output = worker.run_tests(['tests/test_ai_speaker.py'], full_suite=False)\n"
            "    assert passed\n"
            "    pytest_call = next(cmd for cmd in calls if cmd[2:] and cmd[2] == 'pytest')\n"
            "    assert pytest_call == [worker.sys.executable, '-m', 'pytest', '-q', '--tb=native', 'tests/test_ai_speaker.py']\n"
            "    assert 'targeted pytest:' in output\n\n\n"
        )
        if len(anchor) > 1200 or len(test + anchor) > 1800:
            return None, "deterministic_plan_too_large"
        candidate = text.replace(anchor, test + anchor, 1)
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": test + anchor}],
        }, None

    if task_id == "ai-speaker-empty-transcript-no-brain-call" and chosen == "tests/test_ai_speaker.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        function_start = text.find("def test_ai_speaker_rejects_empty_transcript(")
        if function_start < 0:
            return None, f"existing_test_missing:{chosen}"
        next_function = text.find("\ndef ", function_start + 1)
        function_end = next_function if next_function >= 0 else len(text)
        existing_test = text[function_start:function_end]
        if "assert brain.requests == []" in existing_test:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None

        # Match a stable body line, not the exact function signature: existing
        # tests may use annotations or omit them. Strengthen the existing test
        # instead of inserting a duplicate test function.
        anchor = '        raise AssertionError("empty transcript must fail closed")\n'
        if text.count(anchor) != 1:
            return None, f"anchor_count_{chosen}:{text.count(anchor)}"
        new = anchor + "    assert brain.requests == []\n"
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"
        candidate = text.replace(anchor, new, 1)
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "recovery-ai-state-isolation" and chosen == "tests/test_recovery_ai.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_recovery_ai_state_isolation_between_task_ids"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None

        anchor = "def test_same_deterministic_failure_is_not_repaired_repeatedly(tmp_path):\n"
        if text.count(anchor) != 1:
            return None, f"anchor_count_{chosen}:{text.count(anchor)}"
        addition = (
            "def test_recovery_ai_state_isolation_between_task_ids(tmp_path):\n"
            '    store = RecoveryStore(tmp_path / "state.json")\n'
            '    first = store.record_failure("task-a", "timeout", ["tests/test_x.py::test_y"])\n'
            '    second = store.record_failure("task-b", "timeout", ["tests/test_x.py::test_y"])\n'
            '    assert first.task_id == "task-a"\n'
            '    assert second.task_id == "task-b"\n'
            '    assert first.fingerprint != second.fingerprint\n'
            '    assert first.action == "REPAIR_ONCE"\n'
            '    assert second.action == "REPAIR_ONCE"\n'
            '    assert store.task_status("task-a")["consecutive_failures"] == 1\n'
            '    assert store.task_status("task-b")["consecutive_failures"] == 1\n'
            '    assert store.task_status("task-a")["last_category"] == "timeout"\n'
            '    assert store.task_status("task-b")["last_category"] == "timeout"\n'
        )
        new = addition + "\n\n" + anchor
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"
        candidate = text.replace(anchor, new, 1)
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "hand-sign-uhip-contract-phase-start" and chosen == "uhip/tests/test_schema_contracts.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_universal_event_accepts_hand_event_with_phase_start"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None

        anchor = "    validate(event, EVENT_SCHEMA)\n\n\ndef test_universal_event_rejects_application_specific_command():\n"
        count = text.count(anchor)
        if count != 1:
            return None, f"anchor_count_{chosen}:{count}"

        addition = (
            "\n\ndef test_universal_event_accepts_hand_event_with_phase_start():\n"
            "    event = {\n"
            '        "schema_version": "0.3",\n'
            '        "event_id": "0192f0f8-7d4a-7c1b-9d4e-7d9d3c7c9f17",\n'
            '        "session_id": "session-phase-start",\n'
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
            '            "phase": "start",\n'
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
            "        },\n"
            '        "gate": {\n'
            '            "recognition_passed": True,\n'
            '            "rule_version": "phase0-1",\n'
            "        },\n"
            '        "ttl_ms": 500,\n'
            "    }\n"
            "    validate(event, EVENT_SCHEMA)\n"
        )
        new = "    validate(event, EVENT_SCHEMA)\n" + addition + "\n\ndef test_universal_event_rejects_application_specific_command():\n"
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

    if task_id == "hand-sign-uhip-contract-left-hand" and chosen == "uhip/tests/test_schema_contracts.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_universal_event_accepts_hand_event_with_left_hand"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None

        anchor = "def test_universal_event_rejects_application_specific_command():\n"
        count = text.count(anchor)
        if count != 1:
            return None, f"anchor_count_{chosen}:{count}"

        addition = (
            "\n\ndef test_universal_event_accepts_hand_event_with_left_hand():\n"
            "    event = {\n"
            '        "schema_version": "0.3",\n'
            '        "event_id": "0192f0f8-7d4a-7c1b-9d4e-7d9d3c7c9f18",\n'
            '        "session_id": "session-left-hand",\n'
            '        "device_id": "device-1",\n'
            '        "seq": 3,\n'
            '        "t_mono_ns": 300,\n'
            '        "t_wall": "2026-09-28T01:00:02Z",\n'
            '        "source": {\n'
            '            "device_kind": "mac",\n'
            '            "sensor": "camera",\n'
            '            "engine": "mediapipe",\n'
            '            "engine_version": "0.1",\n'
            '            "model_sha256": "a" * 64,\n'
            "        },\n"
            '        "modality": "hand",\n'
            '        "payload": {\n'
            '            "gesture": "open_palm",\n'
            '            "phase": "end",\n'
            '            "value": None,\n'
            '            "hand": {\n'
            '                "label": "left",\n'
            '                "track_id": 5,\n'
            '                "mirrored": False,\n'
            "            },\n"
            '            "confidence": {\n'
            '                "raw": 0.96,\n'
            '                "calibrated": 0.94,\n'
            "            },\n"
            "        },\n"
            '        "gate": {\n'
            '            "recognition_passed": True,\n'
            '            "rule_version": "phase0-1",\n'
            "        },\n"
            '        "ttl_ms": 500,\n'
            "    }\n"
            "    validate(event, EVENT_SCHEMA)\n"
        )
        new = addition + anchor
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"
        candidate = text.replace(anchor, new, 1)
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"

        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "router-regression-jobs-market-metadata" and chosen == "tests/test_management_router.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_routes_jobs_and_market_request_with_market_priority_metadata"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None

        anchor = "def test_preserves_multi_specialist_candidates_and_priority() -> None:\n"
        count = text.count(anchor)
        if count != 1:
            return None, f"anchor_count_{chosen}:{count}"

        addition = (
            "\n\ndef test_routes_jobs_and_market_request_with_market_priority_metadata() -> None:\n"
            '    decision = route(ManagementRequest("u", "JobsとNYダウの情報を一緒に教えて"))\n'
            '    assert decision.specialist is Specialist.MARKET\n'
            '    assert decision.metadata["matched_specialists"] == ["market", "jobs"]\n'
            '    assert decision.metadata["routing_priority"] == 4\n'
        )
        new = addition + anchor
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"

        candidate = text.replace(anchor, new, 1)
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"

        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "router-regression-english-casefold" and chosen == "tests/test_management_router.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_routes_mixed_case_english_request_for_distributed_loop"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None

        anchor = "def test_preserves_multi_specialist_candidates_and_priority() -> None:\n"
        count = text.count(anchor)
        if count != 1:
            return None, f"anchor_count_{chosen}:{count}"

        addition = (
            "\n\ndef test_routes_mixed_case_english_request_for_distributed_loop() -> None:\n"
            '    assert route(ManagementRequest("u", "eNgLiShで会話したい")).specialist is Specialist.ENGLISH\n'
        )
        new = addition + anchor
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"

        candidate = text.replace(anchor, new, 1)
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"

        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

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
        prefix = before.rstrip("\n")
        prior_nonblank = prefix.splitlines()[-1].strip() if prefix.splitlines() else ""
        if prior_nonblank.startswith("@") or prior_nonblank.startswith("#"):
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

    if task_id == "hand-sign-uhip-contract-iphone-camera" and chosen == "uhip/tests/test_schema_contracts.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_universal_event_accepts_iphone_camera_hand_event"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None
        anchor = "    validate(event, EVENT_SCHEMA)\n\n\ndef test_universal_event_rejects_application_specific_command():\n"
        if text.count(anchor) != 1:
            return None, f"anchor_count_{chosen}:{text.count(anchor)}"
        addition = (
            "\n\ndef test_universal_event_accepts_iphone_camera_hand_event():\n"
            "    event = {\n"
            '        "schema_version": "0.3",\n'
            '        "event_id": "0192f0f8-7d4a-7c1b-9d4e-7d9d3c7c9f15",\n'
            '        "session_id": "session-iphone",\n'
            '        "device_id": "iphone-1",\n'
            '        "seq": 2,\n'
            '        "t_mono_ns": 200,\n'
            '        "source": {\n'
            '            "device_kind": "iphone",\n'
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
            '            "hand": {"label": "right", "track_id": 3, "mirrored": True},\n'
            '            "confidence": {"raw": 0.99, "calibrated": 0.97},\n'
            "        },\n"
            '        "gate": {"recognition_passed": True, "rule_version": "phase0-1"},\n'
            '        "ttl_ms": 500,\n'
            "    }\n"
            "    validate(event, EVENT_SCHEMA)\n"
        )
        new = "    validate(event, EVENT_SCHEMA)\n" + addition + "\n\ndef test_universal_event_rejects_application_specific_command():\n"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "hand-sign-uhip-contract-unknown-hand-label" and chosen == "uhip/tests/test_schema_contracts.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_universal_event_accepts_unknown_hand_label"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None
        anchor = "    validate(event, EVENT_SCHEMA)\n\n\ndef test_universal_event_rejects_application_specific_command():\n"
        if text.count(anchor) != 1:
            return None, f"anchor_count_{chosen}:{text.count(anchor)}"
        addition = (
            "\n\ndef test_universal_event_accepts_unknown_hand_label():\n"
            "    event = {\n"
            '        "schema_version": "0.3",\n'
            '        "event_id": "0192f0f8-7d4a-7c1b-9d4e-7d9d3c7c9f16",\n'
            '        "session_id": "session-unknown-hand",\n'
            '        "device_id": "iphone-1",\n'
            '        "seq": 3,\n'
            '        "t_mono_ns": 300,\n'
            '        "source": {"device_kind": "iphone", "sensor": "camera", "engine": "mediapipe", "engine_version": "0.1", "model_sha256": "a" * 64},\n'
            '        "modality": "hand",\n'
            '        "payload": {\n'
            '            "gesture": "open_palm",\n'
            '            "phase": "end",\n'
            '            "value": None,\n'
            '            "hand": {"label": "unknown", "track_id": 4, "mirrored": False},\n'
            '            "confidence": {"raw": 0.80, "calibrated": 0.78},\n'
            "        },\n"
            '        "gate": {"recognition_passed": True, "rule_version": "phase0-1"},\n'
            '        "ttl_ms": 500,\n'
            "    }\n"
            "    validate(event, EVENT_SCHEMA)\n"
        )
        new = "    validate(event, EVENT_SCHEMA)\n" + addition + "\n\ndef test_universal_event_rejects_application_specific_command():\n"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "router-regression-casefold-english" and chosen == "tests/test_management_router.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_routes_mixed_case_english_request"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None
        anchor = '    assert decision.confidence == 0.95\n\n\ndef test_preserves_multi_specialist_candidates_and_priority() -> None:\n'
        if text.count(anchor) != 1:
            return None, f"anchor_count_{chosen}:{text.count(anchor)}"
        addition = (
            "\n\ndef test_routes_mixed_case_english_request() -> None:\n"
            '    assert route(ManagementRequest("u", "eNgLiShで会話したい")).specialist is Specialist.ENGLISH\n'
        )
        new = '    assert decision.confidence == 0.95\n' + addition + "\n\ndef test_preserves_multi_specialist_candidates_and_priority() -> None:\n"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "router-regression-mixed-specialists" and chosen == "tests/test_management_router.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_preserves_market_priority_over_jobs_for_mixed_request"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None
        anchor = '    assert decision.metadata["request_metadata"]["source"] == "parallel-dev-test"\n'
        if text.count(anchor) != 1:
            return None, f"anchor_count_{chosen}:{text.count(anchor)}"
        addition = (
            "\n\ndef test_preserves_market_priority_over_jobs_for_mixed_request() -> None:\n"
            '    decision = route(ManagementRequest("u", "求人とNYダウについて教えて"))\n'
            '    assert decision.specialist is Specialist.MARKET\n'
            '    assert decision.metadata["matched_specialists"] == ["market", "jobs"]\n'
            '    assert decision.metadata["routing_priority"] == 4\n'
        )
        new = anchor + addition
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "uhip-confidence-boundary-acceptance" and chosen == "uhip/tests/test_schema_contracts.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_universal_event_accepts_confidence_boundary_values"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None
        anchor = "def test_universal_event_rejects_application_specific_command():\n"
        if text.count(anchor) != 1:
            return None, f"anchor_count_{chosen}:{text.count(anchor)}"
        addition = (
            "def test_universal_event_accepts_confidence_boundary_values():\n"
            "    event = {\n"
            '        "schema_version": "0.3",\n'
            '        "event_id": "confidence-boundary-acceptance-20261009",\n'
            '        "session_id": "confidence-boundary-session-20261009",\n'
            '        "device_id": "device-1",\n'
            '        "seq": 1,\n'
            '        "t_mono_ns": 100,\n'
            '        "source": {"device_kind": "mac", "sensor": "camera", "engine": "mediapipe", "engine_version": "0.1", "model_sha256": "a" * 64},\n'
            '        "modality": "hand",\n'
            '        "payload": {"confidence": {"raw": 1.0, "calibrated": 0.0}},\n'
            '        "gate": {"recognition_passed": True, "rule_version": "phase0-1"},\n'
            '        "ttl_ms": 500,\n'
            "    }\n"
            "    validate(event, EVENT_SCHEMA)\n\n\n"
        )
        new = addition + anchor
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"
        candidate = text.replace(anchor, new, 1)
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "uhip-confidence-out-of-range-rejection" and chosen == "uhip/tests/test_schema_contracts.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_universal_event_rejects_out_of_range_calibrated_confidence"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None
        anchor = "def test_universal_event_rejects_application_specific_command():\n"
        if text.count(anchor) != 1:
            return None, f"anchor_count_{chosen}:{text.count(anchor)}"
        addition = (
            "def test_universal_event_rejects_out_of_range_calibrated_confidence():\n"
            "    event = {\n"
            '        "schema_version": "0.3",\n'
            '        "event_id": "confidence-range-rejection-20261009",\n'
            '        "session_id": "confidence-range-session-20261009",\n'
            '        "device_id": "device-1",\n'
            '        "seq": 4,\n'
            '        "t_mono_ns": 400,\n'
            '        "t_wall": "2026-09-28T01:00:04Z",\n'
            '        "source": {"device_kind": "mac", "sensor": "camera", "engine": "mediapipe", "engine_version": "0.1", "model_sha256": "a" * 64},\n'
            '        "modality": "hand",\n'
            '        "payload": {"gesture": "thumb_up", "phase": "end", "value": None, "hand": {"label": "right", "track_id": 3, "mirrored": True}, "confidence": {"raw": 0.99, "calibrated": 1.01}},\n'
            '        "gate": {"recognition_passed": True, "rule_version": "phase0-1"},\n'
            '        "ttl_ms": 500,\n'
            "    }\n"
            "    with pytest.raises(jsonschema.ValidationError):\n"
            "        validate(event, EVENT_SCHEMA)\n\n\n"
        )
        new = addition + anchor
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"
        candidate = text.replace(anchor, new, 1)
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "router-regression-stock-jobs-priority" and chosen == "tests/test_management_router.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_router_regression_stock_jobs_priority_distributed_loop"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None
        anchor = "def test_preserves_market_priority_over_jobs_for_mixed_request() -> None:\n"
        count = text.count(anchor)
        if count != 1:
            return None, f"anchor_count_{chosen}:{count}"
        addition = (
            "\n\ndef test_router_regression_stock_jobs_priority_distributed_loop() -> None:\n"
            '    decision = route(ManagementRequest("u", "Find stock prices and job opportunities"))\n'
            "    assert decision.specialist is Specialist.STOCKS\n"
            '    assert decision.metadata["matched_specialists"] == ["stocks", "jobs"]\n'
            '    assert decision.metadata["routing_priority"] == 5\n'
        )
        new = addition + anchor
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"
        candidate = text.replace(anchor, new, 1)
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "router-regression-market-channel-metadata" and chosen == "tests/test_management_router.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_router_regression_market_channel_metadata_distributed_loop"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None
        anchor = "def test_normalizes_full_width_input_and_preserves_channel_metadata() -> None:\n"
        count = text.count(anchor)
        if count != 1:
            return None, f"anchor_count_{chosen}:{count}"
        addition = (
            "\n\ndef test_router_regression_market_channel_metadata_distributed_loop() -> None:\n"
            '    request = ManagementRequest("u", "Explain FOREX exchange rates", channel="line", metadata={"source": "distributed-loop-regression"})\n'
            "    decision = route(request)\n"
            "    assert decision.specialist is Specialist.MARKET\n"
            '    assert decision.metadata["matched_specialists"] == ["market"]\n'
            '    assert decision.metadata["routing_priority"] == 4\n'
            '    assert decision.metadata["channel"] == "line"\n'
            '    assert decision.metadata["request_metadata"]["source"] == "distributed-loop-regression"\n'
        )
        new = addition + anchor
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"
        candidate = text.replace(anchor, new, 1)
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "macos-readiness-audit-no-secret-leak" and chosen == "tests/test_macos_kanban_obsidian_readiness.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_readiness_report_never_exposes_bridge_key"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None
        anchor = "def test_load_env_file_ignores_comments_and_strips_quotes(tmp_path: Path):\n"
        count = text.count(anchor)
        if count != 1:
            return None, f"anchor_count_{chosen}:{count}"
        addition = (
            "\n\ndef test_readiness_report_never_exposes_bridge_key(monkeypatch, tmp_path: Path):\n"
            "    vault = tmp_path / \"vault\"\n"
            "    vault.mkdir()\n"
            '    monkeypatch.setenv("OBSIDIAN_BRIDGE_SERVER_URL", "https://example.invalid")\n'
            '    monkeypatch.setenv("OBSIDIAN_BRIDGE_KEY", "secret-canary-never-logged")\n'
            '    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))\n'
            '    monkeypatch.delenv("HERMES_KANBAN_HOME", raising=False)\n'
            '    monkeypatch.delenv("HERMES_KANBAN_DB", raising=False)\n'
            "\n"
            "    report = readiness.collect_checks(home=tmp_path)\n"
            "    rendered = repr(report)\n"
            "\n"
            '    assert "secret-canary-never-logged" not in rendered\n'
            '    assert report["external_requests"] == 0\n'
            '    assert report["project_writes"] == 0\n'
        )
        new = addition + anchor
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"
        candidate = text.replace(anchor, new, 1)
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id in {"router-regression-general-request-metadata", "router-regression-general-request-metadata-refresh-20261015"} and chosen == "tests/test_management_router.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_router_regression_general_request_keeps_channel_and_request_metadata"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None
        anchor = "def test_unresolved_request_records_empty_candidates() -> None:\n"
        count = text.count(anchor)
        if count != 1:
            return None, f"anchor_count_{chosen}:{count}"
        addition = (
            "def test_router_regression_general_request_keeps_channel_and_request_metadata() -> None:\n"
            '    request = ManagementRequest("u", "今日は何をしよう？", channel="line", metadata={"source": "distributed-loop-general-metadata"})\n'
            "    decision = route(request)\n"
            "    assert decision.specialist is Specialist.GENERAL\n"
            '    assert decision.metadata["routing"] == "deterministic"\n'
            '    assert decision.metadata["matched_specialists"] == []\n'
            '    assert decision.metadata["routing_priority"] is None\n'
            '    assert decision.metadata["channel"] == "line"\n'
            '    assert decision.metadata["request_metadata"]["source"] == "distributed-loop-general-metadata"\n'
            "\n\n"
        )
        new = addition + anchor
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"
        candidate = text.replace(anchor, new, 1)
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "recovery-ai-loop-adapter-durable-state-readback" and chosen == "tests/test_recovery_ai_loop_adapter.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_failure_record_survives_new_store_readback"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None
        anchor = "def test_invalid_evidence_holds_for_human_review(tmp_path):\n"
        count = text.count(anchor)
        if count != 1:
            return None, f"anchor_count_{chosen}:{count}"
        addition = (
            "def test_failure_record_survives_new_store_readback(tmp_path):\n"
            '    path = tmp_path / "recovery.json"\n'
            "    result = record_loop_outcome(path, {\n"
            '        "task_id": "recovery-readback-task", "status": "FAIL", "exit_code": 1,\n'
            '        "failure_reason": "task_timeout",\n'
            "    })\n"
            '    assert result["decision"]["action"] == "REPAIR_ONCE"\n'
            "    reopened = RecoveryStore(path)\n"
            '    status = reopened.task_status("recovery-readback-task")\n'
            '    assert status["consecutive_failures"] == 1\n'
            '    assert status["last_category"] == "timeout"\n'
            '    assert status["same_fingerprint_attempts"] == 1\n'
            "\n\n"
        )
        new = addition + anchor
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"
        candidate = text.replace(anchor, new, 1)
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "loop-test-recovery-state-isolation" and chosen == "tests/test_minimal_autonomous_loop.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        marker = 'RecoveryStore(tmp_path / "recovery-ai-state.json")'
        if marker in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None
        old = '    assert json.loads(lines[0])["task_id"] == "t1"\n'
        count = text.count(old)
        if count != 1:
            return None, f"anchor_count_{chosen}:{count}"
        new = (
            old
            + '    from scripts.recovery_ai import RecoveryStore\n'
            + '    recovery = RecoveryStore(tmp_path / "recovery-ai-state.json")\n'
            + '    status = recovery.task_status("t1")\n'
            + '    assert status["consecutive_failures"] == 1\n'
            + '    assert status["last_category"] == "unknown"\n'
        )
        candidate = text.replace(old, new, 1)
        if len(old) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(old)}, new={len(new)}"
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": old, "new": new}],
        }, None

    if task_id == "loop-refill-empty-catalog-next-safe-test-20261023" and chosen == "tests/test_autonomous_task_refill.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_refill_selects_only_incomplete_unheld_unreviewed_catalog_tasks_within_cap"
        if f"def {name}(" in text:
            return {"no_change": True, "source": "deterministic_autonomous_task"}, None
        anchor = "def test_refill_reports_catalog_exhaustion_by_durable_state(tmp_path: Path):\\n"
        if text.count(anchor) != 1:
            return None, f"anchor_count_{chosen}:{text.count(anchor)}"
        addition = "\\n".join([
            f"def {name}(tmp_path: Path):",
            "    queue, catalog, _ = _inputs(",
            "        tmp_path,",
            "        max_tasks=2,",
            '        existing=[_task("task-existing")],',
            '        candidates=[_task("task-done"), _task("task-held"), _task("task-review"), _task("task-ready-one"), _task("task-ready-two")],',
            "    )",
            "    state = _write(",
            '        tmp_path / "state.json",',
            "        {",
            '            "version": 1,',
            '            "completed": ["task-done"],',
            '            "recovery_ai": {"schema_version": 1, "tasks": {',
            '                "task-held": {"held": True},',
            '                "task-review": {"resume_requires_review": True},',
            '            }, "checkpoint": None},',
            "        },",
            "    )",
            '    output = tmp_path / "runtime.json"',
            "    report = build_queue(queue, catalog, state, output)",
            '    result = json.loads(output.read_text(encoding="utf-8"))',
            '    assert [task["id"] for task in result["tasks"]] == ["task-existing", "task-ready-one"]',
            '    assert report["added_ids"] == ["task-ready-one"]',
            '    assert report["skipped_catalog_completed_ids"] == ["task-done"]',
            '    assert report["skipped_catalog_held_ids"] == ["task-held"]',
            '    assert report["skipped_catalog_review_ids"] == ["task-review"]',
            "",
            "",
        ]) + "\\n"
        new = addition + "\\n" + anchor
        if len(anchor) > 1200 or len(new) > 1800:
            return None, f"deterministic_plan_too_large: old={len(anchor)}, new={len(new)}"
        candidate = text.replace(anchor, new, 1)
        try:
            compile(candidate, chosen, "exec")
        except (SyntaxError, IndentationError) as exc:
            return None, f"deterministic_plan_invalid:{type(exc).__name__}:{exc.msg}"
        return {
            "no_change": False,
            "source": "deterministic_autonomous_task",
            "changes": [{"file": chosen, "old": anchor, "new": new}],
        }, None

    if task_id == "refill-all-catalog-candidates-ineligible-regression" and chosen == "tests/test_autonomous_task_refill.py":
        target = worker.ROOT / chosen
        text = target.read_text(encoding="utf-8")
        name = "test_refill_reports_catalog_exhaustion_by_durable_state"
        if f"def {name}(" not in text:
            return None, "required_regression_test_missing"
        return {"no_change": True, "source": "deterministic_autonomous_task"}, None

    return None, None

class DevelopmentExecutor:
    """Execute concrete development roles against one guarded worktree."""

    def __init__(self, state: DevelopmentState) -> None:
        self.state = state

    def execute(self, task: AgentTask) -> AgentResult:
        try:
            if task.role is AgentRole.MANAGER:
                autonomous_task_id = self.state.autonomous_task_id.strip() or os.environ.get("AUTONOMOUS_TASK_ID", "").strip()
                expected_target = _DETERMINISTIC_AUTONOMOUS_TASK_TARGETS.get(autonomous_task_id)
                files = worker.repo_files()
                if expected_target is not None:
                    # Deterministic queue tasks use their declared target directly;
                    # never call the model-backed file selector for these tasks.
                    if expected_target not in files:
                        return AgentResult(
                            task.task_id,
                            False,
                            f"deterministic target unavailable or disallowed: {expected_target}",
                        )
                    chosen = expected_target
                else:
                    chosen = worker.choose_file(self.state.client, self.state.instruction, files)
                    if not chosen:
                        chosen = _fallback_safe_target(files)
                if not chosen:
                    return AgentResult(task.task_id, False, "manager could not select a safe target")
                self.state.chosen = chosen
                if expected_target is not None and chosen != expected_target:
                    self.state.chosen = None
                    return AgentResult(
                        task.task_id,
                        False,
                        f"deterministic target mismatch: expected {expected_target}, got {chosen}",
                    )
                return AgentResult(task.task_id, True, f"selected {chosen}", frozenset({chosen}))
            if self.state.chosen is None:
                return AgentResult(task.task_id, False, "manager selection missing")
            if task.role is AgentRole.IMPLEMENTER:
                task_id = _autonomous_task_id_for_state(self.state)
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
                task_id = _autonomous_task_id_for_state(self.state)
                deterministic_no_change = (
                    isinstance(self.state.plan, dict)
                    and self.state.plan.get("source") == "deterministic_autonomous_task"
                    and self.state.plan.get("no_change") is True
                    and not self.state.touched
                )
                if deterministic_no_change:
                    target = self.state.chosen
                    if not _is_deterministic_autonomous_task(task_id, target):
                        return AgentResult(task.task_id, False, "deterministic no-change target identity mismatch")
                    passed, output = worker.run_tests([target], full_suite=False)
                else:
                    passed, output = worker.run_tests(self.state.touched or [])
                self.state.tests_passed = passed; self.state.test_output = output
                return AgentResult(task.task_id, passed, output[-4000:], frozenset(self.state.touched or []))
            if task.role is AgentRole.DEBUGGER:
                task_id = _autonomous_task_id_for_state(self.state)
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
                task_id = _autonomous_task_id_for_state(self.state)
                if _is_deterministic_autonomous_task(task_id, self.state.chosen):
                    return AgentResult(task.task_id, True, "no refactor needed for deterministic test task")
                if _is_deterministic_comment_request(self.state.instruction, self.state.chosen):
                    return AgentResult(task.task_id, True, "no refactor needed for deterministic comment change")
                refactor_instruction = (
                    "Refactor the current implementation for clarity, maintainability, "
                    "and duplication reduction. Preserve behavior and satisfy the original request. "
                    f"Original request: {self.state.instruction} "
                    f"Current repair task context: {task.instruction}"
                )
                refactor_context = self.state.test_output
                if task.instruction:
                    refactor_context = (
                        f"{refactor_context}\n\nCurrent repair task context:\n{task.instruction}"
                        if refactor_context
                        else f"Current repair task context:\n{task.instruction}"
                    )
                plan = worker.build_plan(
                    self.state.client,
                    refactor_instruction,
                    self.state.chosen,
                    worker.context_for(self.state.chosen),
                    refactor_context,
                )
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
                task_id = _autonomous_task_id_for_state(self.state)
                if _is_deterministic_autonomous_task(task_id, self.state.chosen):
                    return AgentResult(
                        task.task_id,
                        False,
                        "deterministic test failure; no LLM repair",
                    )
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
    autonomous_task_id = os.environ.get("AUTONOMOUS_TASK_ID", "").strip()
    deterministic_task = autonomous_task_id in _DETERMINISTIC_AUTONOMOUS_TASK_TARGETS
    if deterministic_task:
        # Queue tasks with explicit deterministic plans require no ideation stage.
        instruction, idea_task_id, idea_block_reason = instruction, None, None
    else:
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
    # Deterministic queue tasks must run with no provider client and no API key.
    # If a deterministic plan unexpectedly needs a model, the guarded executor
    # fails closed instead of falling back to an external service.
    client = None if deterministic_task else worker.Groq(api_key=os.environ["GROQ_API_KEY"])
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
    improvement_result = observe_self_improvement(
        report,
        state.chosen,
        allow_external_ai=not deterministic_task,
    )
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
    pushed, publish_detail = _push_development_branch(branch)
    if not pushed:
        print(publish_detail[-2000:], flush=True)
        return 1
    produced = worker.run(["git", "rev-parse", "HEAD"])
    produced_sha = produced.stdout.strip() if produced.returncode == 0 else None
    deferred = publish_detail == "deferred_to_authenticated_workflow_publisher"
    audit_status = "PREPARED" if deferred else "PASS"
    audit_detail = (
        "local branch prepared; authenticated workflow publisher must verify remote push"
        if deferred else "development branch pushed"
    )
    _write_development_audit_to_google_sheets(
        instruction=instruction,
        status=audit_status,
        target_path=state.chosen,
        branch=branch,
        exit_detail=audit_detail,
        base_sha=baseline_sha,
        produced_sha=produced_sha,
    )
    if deferred:
        print(f"Development branch prepared for authenticated workflow publisher: {branch}", flush=True)
    else:
        print(f"Development branch pushed: {branch}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(execute(os.environ.get("DEV_INSTRUCTION", "").strip()[:worker.MAX_INSTRUCTION_LENGTH]))