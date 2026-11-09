# Control Tower queue/catalog audit — 2026-10-19

## Scope and safety

Read-only audit of the runtime task queue and trusted task catalog on branch `feat/control-tower-runtime-selector-integration`. This is an evidence note for Control Tower/REA Phase 0, not task approval.

- Runtime queue blob SHA: `f17851da93c5a46c0d511e080f0e81763ae88008`
- Trusted catalog blob SHA: `172a9110f41c39417feb7c37479f58b2b4cd3318`
- Runtime queue entries: 23
- Trusted catalog entries: 4
- Exact task-ID intersection: 0
- Duplicate IDs within the inspected queue/catalog: none observed
- No task was registered, executed, edited, or resumed by this audit.

**Decision:** all 23 queue entries remain unregistered and must remain blocked by the Control Tower trust boundary until individually reviewed and explicitly registered. Matching file paths or similar names are not proof of equivalent instructions.

## Queue review findings

| Queue task / group | Existing evidence inspected | Preliminary disposition |
|---|---|---|
| `ai-speaker-empty-transcript-no-brain-call` | `tests/test_ai_speaker.py` already has `test_ai_speaker_rejects_empty_transcript`; queue task additionally requires `FakeBrain.requests` to remain empty | Review the existing assertion before deciding. Potentially already covered; do not register on name alone. |
| Six `hand-sign-uhip-contract-*` tasks | All target `uhip/tests/test_schema_contracts.py`. Existing tests include confidence boundaries, phase-start, and left-hand event cases | Multiple queue IDs share one target and some behavior is visibly already tested. Audit each task's exact acceptance condition; use NO_CHANGE only when the required assertion is demonstrably present. |
| `uhip-confidence-boundary-acceptance`, `uhip-confidence-out-of-range-rejection` | Existing tests `test_universal_event_accepts_confidence_boundary_values` and `test_universal_event_rejects_out_of_range_calibrated_confidence` | Strong existing-coverage candidates; compare assertions to task contract before disposition. |
| `macos-readiness-audit-no-secret-leak` | `tests/test_macos_kanban_obsidian_readiness.py` already has `test_readiness_report_never_exposes_bridge_key` | Likely duplicate coverage; verify the full assertion set before NO_CHANGE. |
| `recovery-ai-loop-adapter-durable-state-readback` | Targets `tests/test_recovery_ai_loop_adapter.py`; requires durable read-back through a new store instance and checks category/fingerprint counters | Specific persistence contract; inspect existing adapter tests before deciding. |
| `recovery-ai-state-isolation` | `tests/test_recovery_ai.py` covers failure streaks, HOLD, fingerprints, and state validation; queue task specifically requires two task IDs to remain isolated in one state file | Distinct acceptance condition unless an existing test proves the two-task isolation invariant. |
| Router case-fold pair: `router-regression-casefold-english`, `router-regression-english-casefold` | Both target `tests/test_management_router.py`; current tests include mixed-case English routing | Likely semantic overlap. Require distinct, explicit acceptance conditions before allowing both. |
| Router general-metadata pair: `router-regression-general-request-metadata`, `router-regression-general-request-metadata-refresh-20261015` | Both target the same test file and ask for deterministic GENERAL routing plus channel/request metadata preservation; catalog already has `router-general-channel-metadata-regression` | High duplicate/overlap risk across queue and trusted catalog. Compare required fields and assertions; never register all three by default. |
| Other router tasks: full-width market, jobs/market metadata, market/channel metadata, mixed specialists, stock/jobs priority, whitespace | Existing `tests/test_management_router.py` already covers full-width input/channel metadata, market/jobs priority, mixed-case English, specialist candidates, unresolved GENERAL routing, and priority | Several requirements overlap existing tests. Each must be checked against its exact acceptance condition; shared test-file scope is not sufficient evidence for registration. |
| `loop-deterministic-nochange-focused-test` | `tests/test_line_development_worker_v2.py` already has `test_run_tests_can_verify_only_allowlisted_target_for_no_change` | Likely existing coverage; verify it asserts the exact `full_suite=False` invocation and target path. |

## Control Tower recommendations

1. Keep the trusted catalog as the only registration authority; the runtime queue must not self-register IDs.
2. Keep normal execution limited to one task until per-task re-selection, produced-HEAD binding, allowed-path validation, and Recovery AI HOLD re-check are implemented and tested.
3. Resolve queue items as one of `REGISTER_AFTER_REVIEW`, `NO_CHANGE`, `DUPLICATE_CANDIDATE`, or `BLOCKED_NEEDS_SPEC`, with links to the exact test/assertion evidence. These are audit labels, not automatic actions.
4. Before registration, verify each task has a narrow allowed-path list, deterministic instruction, bounded test command, no secret/external/OS side effects, and a unique acceptance condition.
5. Do not release existing Recovery AI HOLD based on this audit. Resume requires a verified cause fix and the existing explicit confirmation path.

## Hermes Kanban / Obsidian boundary

Repository code includes a local read-only readiness audit (`scripts/macos_kanban_obsidian_readiness.py`) that checks the Hermes repository, reads `~/.hermes/kanban.db` in SQLite read-only mode, reports status counts without task titles, and suppresses bridge-key values. Tests cover missing DB handling, read-only health checks, missing tables, and secret suppression.

The verified Hermes-to-Obsidian handoff (`core/hermes_obsidian_bridge.py`) accepts only a `source=hermes-kanban`, `status=PASS`, `verified=true` result with both `auto_apply_patch=false` and `auto_deploy=false`; it enqueues a pending Obsidian job rather than writing directly to the vault.

**Runtime limitation:** GitHub inspection cannot establish the current state of the user's Mac-local Kanban database, LaunchAgents, or actual Obsidian note read-back. Those remain `NOT_VERIFIED` until a local readiness report and one end-to-end, user-approved Mac bridge run exist. Do not infer live Kanban counts from old notes.

## Status

This is a read-only review artifact. No queue/catalog changes, task execution, Recovery AI state mutation, HOLD release, merge, or deploy occurred.
