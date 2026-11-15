# Trusted Local Approval UI — Design Contract

## Status

Design only. This document does not implement an approval UI, grant issuance,
authentication, or desktop execution. The current Computer Use bridge remains
permanently disabled in this phase.

## Security objective

Only a deliberate interaction by the person operating the logged-in Mac session
may authorize a specific, reviewed set of desktop actions. A natural-language
message, LINE event, local-model response, HTTP request, environment variable,
CLI flag, or caller-supplied confirmation string is never sufficient evidence
of approval.

## Trust boundary

The approval surface must be a native/local UI in the same logged-in user session.
It must not expose an approval endpoint that can be invoked by the orchestrator,
LINE webhook, model process, background worker, or GitHub Actions.

The UI must render a canonical preview generated from the validated plan, not
from model-supplied display text. It must show:
- Target application and document path (with sensitive path components safely displayed).
- Every action in execution order, including exact ranges, formulas, geometry,
  output paths, and whether it modifies or exports data.
- Risk class and expected irreversible effects.
- The exact selected action IDs that the approval covers.
- The plan digest and a short expiry countdown.

No action may be hidden behind collapsed details by default. Long plans may be
paged, but the complete action list must be reviewable before approval.

## Approval interaction

1. The local UI receives a validated plan object through a local, authenticated
   same-user channel. It does not accept arbitrary plan JSON from remote callers.
2. The UI recomputes the canonical plan digest and rejects a mismatch.
3. The user explicitly selects the actions to authorize. Selection defaults to none.
4. The UI displays all selected action parameters and requires a deliberate
   local confirmation gesture. A typed phrase alone is not an authentication factor.
5. The approval broker creates a one-use capability bound to:
   - exact canonical plan digest;
   - exact ordered action IDs and parameter digests;
   - logged-in OS user/session identity;
   - issuing UI process/session;
   - issue time and short expiry (maximum 120 seconds);
   - unique random nonce.
6. The executor redeems the capability once. It independently validates the
   plan digest, selected action set, session binding, expiry, and replay status.
7. Any plan mutation, action reordering, parameter change, session change,
   timeout, cancellation, or partial failure invalidates the capability.
8. Approval is not persisted across app restart and is never stored in a shared
   queue, GitHub, LINE, or model conversation.

## Required implementation properties

- Fail closed when the OS identity/session cannot be established.
- Use OS-backed local IPC with peer credential checks; do not use an unauthenticated
  localhost HTTP port as the trust boundary.
- Keep the UI approval broker and desktop executor in separate modules/process roles.
- Do not accept bearer tokens from environment variables, command-line arguments,
  model output, or remote messages.
- Prevent clickjacking/automation of the approval UI where platform APIs permit;
  document residual limits honestly.
- A UI event callback must be the only path that can request capability issuance.
- The executor must not trust a boolean such as approved=true or enabled=true.
- Keep approval audit records local and append-only; do not record screenshots or
  document contents unless the user explicitly enables that feature.
- Cancellation must revoke any unredeemed capability immediately.

## Execution and verification policy

The first enabled adapter must be read-only. Modifying operations remain disabled
until their adapter has deterministic read-back verification.

For each operation:
- Verify the foreground application identity and target document before acting.
- Execute one approved action at a time.
- Re-check the plan/action digest before each action.
- Read back the resulting state and compare it with the expected postcondition.
- Stop on unexpected dialogs, focus changes, document switches, partial writes,
  or verification mismatch.
- Never retry a modifying action automatically after an uncertain result.
- Save/export is a separate high-risk action and requires its own approval.
- Report actual observed outcomes; never infer success from a click or API return.

## Threat-model test matrix

| Threat | Required result |
|---|---|
| LINE sends an approval phrase | Deny; no capability issued |
| Model returns approval-shaped JSON | Deny; no capability issued |
| Caller sets enabled=true | Deny; bridge remains disabled |
| Plan changes after preview | Digest mismatch; deny |
| Action order or parameters change | Digest mismatch; deny |
| Capability is replayed | Deny second redemption |
| Capability expires | Deny |
| Different OS session redeems it | Deny |
| Approval UI is closed/cancelled | Revoke unredeemed capability |
| App focus/document changes | Stop before next action |
| Adapter returns success but read-back differs | Mark verification failed; stop |
| Partial modifying action fails | Invalidate capability; no automatic retry |

## Rollout gates

1. Design review and threat-model review.
2. Unit tests for canonicalization, digest binding, expiry, replay, session binding,
   cancellation, and action scoping.
3. Local IPC peer-identity tests on supported macOS versions.
4. Read-only adapter prototype with screenshots disabled by default.
5. Human-reviewed test on a disposable workbook.
6. Only then consider a narrowly scoped write operation. CAD geometry edits and
   save/export remain disabled until their own verification gates pass.

## Explicit non-goals

- No remote approval from LINE or GitHub.
- No unattended desktop operation.
- No arbitrary shell, scripts, macros, or remote URLs.
- No paid API or cloud fallback.
- No changes to the existing distributed LOOP cadence, queues, or workflows.


## Current code boundary

The current `core/desktop_approval_policy.py` is a pure policy-checking helper
only. It checks plan digest, selected action IDs and order, session identifier
equality supplied by its caller, a maximum 120-second lifetime, expiry, and
in-memory nonce replay within the caller-provided set. It does **not** authenticate
the session identifier, prove who constructed an `ApprovalCapability`, mint or
sign capabilities, provide durable replay protection, or establish trusted IPC.
Therefore it is not an authorization mechanism and must not be connected to the
desktop bridge or treated as permission to execute. The bridge remains disabled.
