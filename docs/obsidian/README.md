# Obsidian knowledge bridge

Obsidian is the human-readable knowledge layer for REA, Orca, Hermes, and the distributed loop. GitHub remains canonical for source code, pull requests, workflow runs, and machine-verifiable evidence. A note is an indexed explanation and link to evidence, not a replacement for it.

## Operating contract

1. **Evidence first.** Every operational note must identify its repository and immutable Git commit SHA. Workflow-derived notes should include the workflow run ID and URL when available. REA notes should include the scanner report's evidence digest and coverage state when present.
2. **Separate observation classes.** Keep runtime collector observations distinct from GitHub Actions self-reports, REA repository scans, and artifact validation. Never upgrade a self-report to a runtime observation.
3. **Fail closed.** Missing SHA, missing provenance, incomplete scan coverage, or missing source evidence is recorded as `UNVERIFIED` / `INCOMPLETE`; it is not silently treated as PASS.
4. **No authority.** Notes cannot approve execution, clear HOLD, authorize patch application, merge, deploy, change secrets, or change schedules.
5. **No sensitive payloads.** Do not copy secrets, tokens, user prompts, private task payloads, raw environment variables, or unrestricted logs into the vault. Store short redacted excerpts only when necessary.
6. **Append-only by default.** Create a new note for a new evidence identity. Do not overwrite an existing note automatically. Corrections should link to the superseded note and preserve its history.
7. **Human-readable and portable.** Use plain Markdown with YAML frontmatter and ordinary links. Avoid plugin-specific syntax in the canonical export format.

## Note types

| Type | Purpose | Required evidence |
|---|---|---|
| `rea-finding` | Finding, severity, rationale, unchecked items | repo, commit SHA, finding ID, scanner evidence digest if available |
| `orca-observation` | One stream's runtime observation | source, observation type, captured time, stream key, collector/run reference |
| `workflow-report` | GitHub Actions self-report | repo, workflow name, run ID, head SHA, run URL |
| `decision` | Accepted/rejected design decision | decision ID, date, linked evidence and rationale |
| `improvement` | Root cause and verified remediation | before/after commit SHA, test/run evidence, remaining risks |
| `procedure` | Reusable Hermes/operator procedure | owner, prerequisites, safety boundary, last verified date |

## Suggested vault layout

```text
00_Inbox/
01_Current_State/
02_Development_Log/
03_Design_Spec/
04_REA/
  Findings/
  Scans/
05_Orca/
  Runtime/
  Workflow_Reports/
06_Decisions/
07_Improvements/
08_Hermes_Procedures/
```

This is a suggested mapping, not an instruction to rename or move existing vault folders. Preserve the user's existing vault structure and map these categories into it.

## REA -> Obsidian

For each completed scan, create:
- one scan summary with target SHA, coverage COMPLETE/INCOMPLETE, gate result, evidence digest, counts by severity, and unchecked items;
- one finding note per stable finding ID when findings exist;
- links to the exact PR/commit and source paths.

Do not write a PASS note when the scan is incomplete or the target SHA does not match. Record BLOCKED and the missing evidence instead.

## Orca -> Obsidian

Record each stream separately using its explicit `stream_key`. Preserve:
- `source` and `observation_type`;
- capture timestamp and freshness;
- stream status (observed / reported / unknown);
- run ID or collector reference;
- target SHA and evidence digest when available.

The current provenance labels are claims supplied by the sender. They do not independently prove that a GitHub Actions run exists. Until server-side run verification is implemented, workflow evidence remains `reported`, not `observed`.

## Hermes and local models

Store procedures, failure signatures, model-selection experiments, and verified workarounds. Include model name/version, host context only when non-sensitive, test case, result, and limitations. Do not store secrets or infer successful computer use from a tool invocation alone.

## Rollout

1. Use the templates in this directory to standardize new notes.
2. Generate notes into a staging/export folder first; do not write directly to the vault until the existing Obsidian Bridge path and its no-overwrite behavior have been verified on the Mac.
3. Verify the Bridge's write result and read the note back before marking a sync successful.
4. Report sync state separately: `NOT_CONFIGURED`, `STAGED`, `WRITTEN`, or `READBACK_VERIFIED`.

The repository currently defines the note contract only. It does not claim that the user's local vault has been written.
