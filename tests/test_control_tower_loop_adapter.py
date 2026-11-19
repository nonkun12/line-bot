from __future__ import annotations

from scripts.control_tower_loop_adapter import authorize_registered_task


VALID_SHA = "a" * 40


def task_entry() -> dict[str, object]:
    return {
        "id": "router-regression-safe-case",
        "instruction": "Run a bounded deterministic regression test.",
        "allowed_paths": ["tests/test_management_router.py"],
    }


def test_authorizes_exact_registered_task_against_current_head() -> None:
    task = task_entry()

    assert authorize_registered_task(task, [task], VALID_SHA) == (
        True,
        "registered_task_and_current_head_verified",
    )


def test_rejects_unregistered_task() -> None:
    assert authorize_registered_task(task_entry(), [], VALID_SHA) == (
        False,
        "task_not_uniquely_registered",
    )


def test_rejects_duplicate_registry_ids() -> None:
    task = task_entry()

    assert authorize_registered_task(task, [task, task], VALID_SHA) == (
        False,
        "task_not_uniquely_registered",
    )


def test_rejects_instruction_or_path_tampering_for_registered_id() -> None:
    registered = task_entry()
    tampered = {**registered, "instruction": "run an unreviewed arbitrary task"}

    assert authorize_registered_task(tampered, [registered], VALID_SHA) == (
        False,
        "task_definition_mismatch",
    )

    tampered_path = {**registered, "allowed_paths": ["../../secrets"]}
    assert authorize_registered_task(tampered_path, [registered], VALID_SHA) == (
        False,
        "task_definition_mismatch",
    )


def test_rejects_invalid_or_stale_current_head_sha() -> None:
    task = task_entry()

    assert authorize_registered_task(task, [task], "") == (
        False,
        "invalid_current_head_sha",
    )
    assert authorize_registered_task(task, [task], "B" * 40) == (
        False,
        "invalid_current_head_sha",
    )


def test_rejects_malformed_task_and_registry() -> None:
    task = task_entry()

    assert authorize_registered_task(None, [task], VALID_SHA) == (
        False,
        "invalid_task_registry",
    )
    assert authorize_registered_task(task, "not-a-registry", VALID_SHA) == (
        False,
        "invalid_task_registry",
    )


def test_rejects_task_id_that_decision_contract_cannot_represent() -> None:
    task = {**task_entry(), "id": "../unsafe"}

    assert authorize_registered_task(task, [task], VALID_SHA) == (
        False,
        "decision_contract_rejected",
    )
