# Local Natural-Language Desktop Control: CAD + Excel + Calc

## Current status

The project has a Phase 0 plan validator and a Phase 1 bridge placeholder. No desktop
execution is enabled. The bridge intentionally rejects all execution requests until
a trusted, local, user-interaction approval surface and independently reviewed adapter
are implemented. A caller-supplied phrase, model output, LINE message, or
enabled=True flag is not proof of human approval.

## Scope

- Spreadsheet targets: Microsoft Excel and LibreOffice Calc.
- CAD remains vendor-neutral; no CAD application is selected or installed.
- Mac-local operation only; no paid API, cloud fallback, remote desktop, or credential capture.
- Existing 30-minute LOOP workflows and queues are out of scope and must not be modified.

## Architecture

Japanese natural-language request
→ local model via loopback-only endpoint
→ strict JSON plan validation
→ risk-labelled preview
→ trusted local approval UI (not implemented)
→ narrowly scoped application adapter (not implemented)
→ read-back verification (not implemented)
→ local audit record

## Safety boundary

- The model proposes structured data only; it cannot provide executable code.
- Per-application operation allowlists and bounded parameters are validated.
- Shell commands, scripts, macros, URLs, network paths, arbitrary deletion, and
  unrecognized operations are rejected.
- Read-only inspection and modifying operations are both preview-only at this stage.
- Modifying operations and save/export actions will require explicit, action-scoped
  human approval in a trusted local UI.
- No approval can be minted by a plain string or by a LINE/model request.
- The current bridge rejects snapshot and execution requests. Injecting an adapter
  or setting enabled=True does not enable it.
- The bridge must verify exact plan identity, action scope, expiry, one-time use,
  and post-action read-back before any production enablement.
- No background job or GitHub Action may operate the user's Mac desktop.

## Remaining phases

1. Trusted approval UI: local interactive confirmation bound to exact plan digest
   and selected actions; must not be callable by model/LINE input.
2. Local bridge: authenticated local-session transport with no arbitrary shell access.
3. Application adapters: Excel and Calc first; CAD only after a separate app choice.
4. Execution policy: per-action scope, expiry, one-time authorization, cancellation,
   and safe handling of partial failure.
5. Verification: read-back of cell values, formulas, workbook properties, CAD
   geometry, and save/export destination; report discrepancies without claiming success.
6. Orchestrator/LINE: submit requests and show previews, but never bypass local approval.

## Test scope

The bridge tests should prove that the placeholder remains disabled even when an
adapter is injected or enabled=True is passed. They do not prove desktop integration.
