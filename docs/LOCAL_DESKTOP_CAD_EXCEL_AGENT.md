# Local Natural-Language Desktop Control: CAD + Excel

## Goal

Provide a local-first Computer Use system that accepts natural-language requests and
operates CAD and spreadsheet applications through a guarded desktop runner.

Initial targets:
- CAD: FreeCAD (structured geometry/API adapter first; screen interaction as fallback).
- Spreadsheet: Microsoft Excel (native application adapter first; screen interaction as fallback).
- Optional later target: LibreOffice Calc through the same spreadsheet contract.

The current implementation in `core/desktop_control.py` is **Phase 0: intent-to-plan**.
It can ask an injected local model for a structured plan and validates every field.
It does not yet control the desktop or modify files.

## Architecture

```text
Natural-language request
        |
        v
Local Orchestrator / intent router
        |
        v
Local model (Ollama loopback only)
        |
        v
Strict JSON plan validator (core/desktop_control.py)
        |
        v
Preview + risk classification + human confirmation
        |
        v
Local Desktop Runner (not enabled in Phase 0)
        |                         |
        v                         v
FreeCAD adapter              Excel adapter
(native API first)           (native API first)
        |                         |
        +------------+------------+
                     v
           Post-action verification
                     |
                     v
          Local audit record + result
```

## Safety contract

- The model proposes structured actions; it never supplies executable code.
- Only the per-application operation allowlists are accepted.
- Shell commands, Python/JavaScript, VBA/macros, URLs, network paths, arbitrary
  file deletion, and unrecognized operations are rejected.
- Spreadsheet formulas that can invoke external data or links are rejected.
- Read-only inspection may be previewed without a modification approval.
- Every modifying operation is marked for human confirmation.
- Save/export operations are high-risk and require explicit confirmation.
- The plan digest binds the exact validated request and actions.
- Phase 0 always returns `execution_authorized=false` and
  `execution_performed=false`.
- The placeholder runner always fails closed. There is no hidden or simulated
  desktop execution.

## Initial supported action vocabulary

### FreeCAD
- `open_document(path)`
- `inspect_model(object_name?)`
- `create_sketch(plane, geometry[])`
- `add_hole(diameter_mm, positions[])`
- `extrude(depth_mm)`
- `export_step(path)`
- `save_as(path)`

### Excel
- `open_workbook(path)`
- `inspect_sheet(sheet_name?)`
- `write_cells(sheet_name, range, values[][])`
- `create_formula(sheet_name, cell, formula)`
- `create_chart(sheet_name, data_range, chart_type)`
- `save_as(path)`

If a request lacks a required dimension, coordinate, cell range, or destination,
the model is instructed to request inspection or clarification rather than invent it.

## Implementation phases

1. **Phase 0 — Plan contract (implemented):** local-model injection, JSON validation,
   operation allowlists, bounds, risk labels, plan digest, fail-closed runner.
2. **Phase 1 — Local Computer Use runner:** user-session-only process; accessibility
   permission check; screenshots and UI element inspection; no remote desktop,
   no cloud fallback, no credential capture. All operations remain disabled until
   the user explicitly enables the local runner.
3. **Phase 2 — Native application adapters:** FreeCAD Python API and Excel
   AppleScript/Office automation adapter, with GUI fallback only where needed.
4. **Phase 3 — Verification:** reopen/read-back, geometry and cell-value checks,
   save-path confirmation, screenshot evidence, append-only local audit trail.
5. **Phase 4 — Orchestrator/LINE interface:** natural-language task submission,
   plan preview, approval, progress and result reporting. LINE must not bypass
   local confirmation or execute while the local runner is offline.

## Runtime constraints

- Local model endpoint must remain loopback-only (reuse
  `core/local_model_adapter.py`); no paid API or cloud fallback.
- No background worker is required for interactive desktop tasks.
- The runner must operate only in the logged-in user's desktop session.
- The four legacy sub-systems remain closed.
- No merge, deploy, remote action dispatch, or permission change is part of this work.

## Phase 0 test

Run:

```bash
pytest -q tests/test_desktop_control.py
```

A passing Phase 0 test proves only that plans are validated and unsafe plans are
rejected. It does not prove that FreeCAD or Excel can be controlled yet.
