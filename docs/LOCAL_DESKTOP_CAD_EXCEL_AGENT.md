# Local Natural-Language Desktop Control: CAD + Excel + Calc

## Goal and scope

Provide a Mac-local Computer Use system that accepts Japanese natural-language requests
and can work with CAD and spreadsheet applications. The preferred architecture uses
native application APIs for precise edits and Computer Use for UI navigation, visual
inspection, and verification.

Targets:
- Spreadsheet: Microsoft Excel **and** LibreOffice Calc.
- CAD: vendor-neutral action contract first. The CAD application is deliberately
  undecided; do not assume FreeCAD or install a CAD package without a later decision.
- Desktop control: local logged-in Mac session only. OpenClaw's local Computer Use
  capability is the preferred integration candidate, subject to a read-only capability
  and permission check on the actual Mac.

The current implementation is **Phase 0: intent-to-plan**. It validates local-model
proposals and returns a preview. It does not control the desktop or modify files.

## Architecture

```text
Japanese natural-language request (chat / LINE)
        |
        v
Existing Orchestrator: intent routing and task decomposition
        |
        v
Local model through loopback-only Ollama adapter
        |
        v
Strict JSON plan validator (core/desktop_control.py)
        |
        v
Plan preview + risk classification + human confirmation
        |
        v
Mac-local Computer Use bridge (not connected yet)
        |
        +-------------------+---------------------+
        v                   v                     v
Excel adapter        LibreOffice adapter     CAD adapter
(native API first)   (UNO/API first)         (vendor-neutral contract)
        |                   |                     |
        +-------------------+---------------------+
                            v
                 Read-back verification
                            |
                            v
                Local audit + user-visible result
```

## Supported plan vocabulary

### CAD (application not selected)
- `open_document(path)`
- `inspect_model(object_name?)`
- `create_sketch(plane, geometry[])`
- `add_hole(diameter_mm, positions[])`
- `extrude(depth_mm)`
- `export_step(path)`
- `save_as(path)`

The plan schema is vendor-neutral. A later CAD selection must map these operations
to that application's native API and report unsupported operations explicitly.

### Excel and LibreOffice Calc
Both spreadsheet targets share the same bounded operations:
- `open_workbook(path)`
- `inspect_sheet(sheet_name?)`
- `write_cells(sheet_name, range, values[][])`
- `create_formula(sheet_name, cell, formula)`
- `create_chart(sheet_name, data_range, chart_type)`
- `save_as(path)`

A target-specific adapter must preserve workbook formulas, styles, merged cells,
named ranges, charts, and unsupported features. It must not silently convert or
discard features when opening/saving across formats.

## Safety contract

- The local model proposes structured data; it never supplies executable code.
- Only per-application operation allowlists are accepted.
- Shell commands, Python/JavaScript, VBA/macros, URLs, network paths, arbitrary
  file deletion, and unrecognized operations are rejected.
- Spreadsheet formulas capable of external data access or links are rejected.
- Numeric CAD geometry and spreadsheet ranges are bounded and validated.
- Read-only inspection can be previewed without modification approval.
- Every modifying operation requires explicit human confirmation.
- Save/export operations are high-risk and require explicit confirmation.
- The plan digest binds the exact validated request and actions.
- Current runner always fails closed: `execution_authorized=false`,
  `execution_performed=false`.
- No background job or GitHub Action may operate the user's Mac desktop.
- No cloud fallback or paid model API. Model endpoint remains loopback-only.

## Implementation phases

1. **Phase 0 — Plan contract (implemented):** Excel, Calc and vendor-neutral CAD
   schemas; JSON validation; bounds; risk labels; digest; fail-closed runner.
2. **Phase 1 — Mac Computer Use bridge:** inspect existing OpenClaw installation,
   desktop capability, accessibility/screen-recording permissions and local tool
   policy. Read-only capability check first; do not change host settings silently.
3. **Phase 2 — App adapters:** Excel and Calc adapters; choose CAD application only
   after a separate decision. Prefer native APIs, use Computer Use for UI-only tasks.
4. **Phase 3 — Approval and execution:** per-action confirmation, scoped file access,
   no arbitrary shell or macro execution, and explicit save/export confirmation.
5. **Phase 4 — Verification:** reopen/read-back, geometry and cell-value checks,
   save-path confirmation, screenshots and append-only local audit records.
6. **Phase 5 — Orchestrator/LINE:** submit natural-language tasks, show previews,
   request approvals, and report verified outcomes. LINE cannot bypass local approval
   or operate the Mac while the local bridge is offline.

## Runtime constraints

- Mac-local, user-session-only operation.
- No paid APIs, cloud fallback, remote desktop, or credential capture.
- No auto-merge, deploy, or reopening of the four legacy sub-systems.
- No install, permission change, or live desktop action as part of this PR.
- The existing 30-minute LOOP work remains a separate priority; this desktop project
  must not consume or modify its runtime queue or scheduling configuration.

## Phase 0 test

Run:

```bash
pytest -q tests/test_desktop_control.py
```

Passing these tests proves only that plans are validated and unsafe plans rejected.
It does not prove that Excel, Calc, CAD, or Mac Computer Use can be controlled yet.
