import hashlib

import pytest

from core.line_task_approval import (
    ApprovalCommand,
    allowed_paths_digest,
    instruction_digest,
    parse_approval_command,
    parse_approval_preview_command,
    sign_approval_envelope,
    sign_preview_challenge,
    validate_approval_request,
    verify_approval_envelope_signature,
)

SECRET = "test-only-line-approval-secret-at-least-32-bytes"
TASK = "review-gap-abc123"
INSTRUCTION = "Add one bounded regression test."
PATHS = ["tests/test_example.py"]
BASE = "a" * 40
USER = "U-authorized-user"
EXPIRY = 1_800_000_300
NOW = 1_800_000_000
NONCE = "b" * 32


def _challenge():
    digest = instruction_digest(INSTRUCTION)
    paths_digest = allowed_paths_digest(PATHS)
    signature = sign_preview_challenge(
        task_id=TASK, instruction_sha256=digest,
        allowed_paths_sha256=paths_digest, base_sha=BASE,
        expires_at=EXPIRY, approver_user_id=USER, nonce=NONCE,
        secret=SECRET,
    )
    command_text = f"実行承認: {TASK} {digest} {BASE} {EXPIRY} {NONCE} {signature}"
    return parse_approval_command(command_text), command_text


def _candidate(**overrides):
    candidate = {
        "task_id": TASK, "catalog_registered": True, "catalog_match": True,
        "execution_approved": True, "instruction": INSTRUCTION,
        "allowed_paths": PATHS, "base_sha": BASE,
    }
    candidate.update(overrides)
    return candidate


def test_parse_preview_and_signed_approval_command():
    assert parse_approval_preview_command(f"承認候補: {TASK}").task_id == TASK
    command, text = _challenge()
    assert command is not None
    assert parse_approval_command(text) == command
    assert parse_approval_command(text + " extra") is None


def test_preview_challenge_is_bound_to_approver_and_fields():
    command, _ = _challenge()
    decision = validate_approval_request(
        command, user_id=USER, allowed_user_ids={USER},
        candidate=_candidate(), now_epoch=NOW, secret=SECRET,
    )
    assert decision.nonce == NONCE
    assert decision.expires_at == EXPIRY
    assert decision.allowed_paths_sha256 == allowed_paths_digest(PATHS)
    assert sign_approval_envelope(decision, secret=SECRET)


@pytest.mark.parametrize("field,value", [
    ("instruction_sha256", "c" * 64),
    ("base_sha", "d" * 40),
    ("expires_at", EXPIRY + 1),
    ("nonce", "e" * 32),
    ("challenge_signature", "f" * 64),
])
def test_tampered_preview_challenge_is_rejected(field, value):
    command, _ = _challenge()
    tampered = ApprovalCommand(
        command.task_id,
        value if field == "instruction_sha256" else command.instruction_sha256,
        value if field == "base_sha" else command.base_sha,
        value if field == "expires_at" else command.expires_at,
        value if field == "nonce" else command.nonce,
        value if field == "challenge_signature" else command.challenge_signature,
    )
    with pytest.raises(ValueError):
        validate_approval_request(
            tampered, user_id=USER, allowed_user_ids={USER},
            candidate=_candidate(), now_epoch=NOW, secret=SECRET,
        )


def test_preview_expiry_is_enforced_and_not_user_selected():
    command, _ = _challenge()
    with pytest.raises(ValueError, match="expired"):
        validate_approval_request(
            command, user_id=USER, allowed_user_ids={USER},
            candidate=_candidate(), now_epoch=EXPIRY, secret=SECRET,
        )
    with pytest.raises(ValueError, match="five-minute"):
        validate_approval_request(
            command, user_id=USER, allowed_user_ids={USER},
            candidate=_candidate(), now_epoch=NOW - 1, secret=SECRET,
        )


def test_catalog_and_user_mismatches_fail_closed():
    command, _ = _challenge()
    with pytest.raises(ValueError, match="unauthorized"):
        validate_approval_request(
            command, user_id="U-other", allowed_user_ids={USER},
            candidate=_candidate(), now_epoch=NOW, secret=SECRET,
        )
    with pytest.raises(ValueError, match="catalog"):
        validate_approval_request(
            command, user_id=USER, allowed_user_ids={USER},
            candidate=_candidate(catalog_match=False), now_epoch=NOW, secret=SECRET,
        )


def test_runtime_envelope_signature_rejects_field_tampering():
    command, _ = _challenge()
    decision = validate_approval_request(
        command, user_id=USER, allowed_user_ids={USER},
        candidate=_candidate(), now_epoch=NOW, secret=SECRET,
    )
    signature = sign_approval_envelope(decision, secret=SECRET)
    common = {
        "task_id": TASK, "instruction_sha256": instruction_digest(INSTRUCTION),
        "allowed_paths_sha256": allowed_paths_digest(PATHS), "base_sha": BASE,
        "expires_at": EXPIRY, "approver_user_id": USER, "nonce": NONCE,
        "signature": signature, "secret": SECRET,
    }
    assert verify_approval_envelope_signature(**common)
    assert not verify_approval_envelope_signature(**{**common, "nonce": "c" * 32})
    assert not verify_approval_envelope_signature(**{**common, "expires_at": EXPIRY + 1})
    assert not verify_approval_envelope_signature(**{**common, "secret": ""})


def test_same_preview_command_reuses_same_nonce_for_atomic_ledger():
    first, text = _challenge()
    replay = parse_approval_command(text)
    assert first == replay
    assert first.nonce == replay.nonce == NONCE


def test_preview_and_execution_signatures_are_domain_separated():
    command, _ = _challenge()
    decision = validate_approval_request(
        command, user_id=USER, allowed_user_ids={USER},
        candidate=_candidate(), now_epoch=NOW, secret=SECRET,
    )
    preview_signature = command.challenge_signature
    execution_signature = sign_approval_envelope(decision, secret=SECRET)

    assert preview_signature != execution_signature
    assert not verify_approval_envelope_signature(
        task_id=decision.task_id,
        instruction_sha256=decision.instruction_sha256,
        allowed_paths_sha256=decision.allowed_paths_sha256,
        base_sha=decision.base_sha,
        expires_at=decision.expires_at,
        approver_user_id=decision.approver_user_id,
        nonce=decision.nonce,
        signature=preview_signature,
        secret=SECRET,
    )


def test_approval_candidate_held_state_is_rejected():
    command, _ = _challenge()
    candidate = {**_candidate(), "task_held": True}
    with pytest.raises(ValueError, match="currently held"):
        validate_approval_request(
            command, user_id=USER, allowed_user_ids={USER},
            candidate=candidate, now_epoch=NOW, secret=SECRET,
        )


def test_approval_challenge_rejects_expiry_over_300_seconds():
    command, _ = _challenge()
    from dataclasses import replace
    extended = replace(command, expires_at=NOW + 301)
    with pytest.raises(ValueError, match="five-minute"):
        validate_approval_request(
            extended, user_id=USER, allowed_user_ids={USER},
            candidate=_candidate(), now_epoch=NOW, secret=SECRET,
        )
