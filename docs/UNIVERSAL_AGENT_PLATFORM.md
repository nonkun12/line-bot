# Universal AI Agent Platform

This design separates the AI Secretary itself from independent software projects and treats Agents as governed, first-class resources.

## Repository policy

- `nonkun12/line-bot` is the AI Secretary and the only self-improvement target.
- One independent software project uses one GitHub repository.
- Render, OCI, and n8n are runtime/orchestration infrastructure.
- GitHub is the source of truth for source code.
- Existing-project changes require deterministic Project Registry resolution.

## Task modes

1. self-improvement;
2. new software project;
3. existing project maintenance;
4. Agent creation or upgrade;
5. non-software work such as research, analysis, reporting, documentation, monitoring, and operations.

## Self-improvement pipeline

Inspect -> Plan -> Implement -> Test -> Review -> Repair -> Integration -> PR -> Merge Gate -> Deploy Gate -> Post Deploy Verification -> Report

Self-improvement must use a PR and must not write directly to main.

## New software pipeline

Requirements -> Project Classification -> Repository Naming -> Repository Creation -> Architecture -> Implementation -> QA -> Review -> Repair -> Integration -> PR -> Merge Gate -> Deploy -> Verification -> Report

New software must remain independent from `line-bot`.

## Agent lifecycle

Generate -> Validate -> Test -> Review -> Enable

A generated Agent declares its name, purpose, input/output contract, allowed tools, resource scope, safety constraints, tests, and registration metadata.

## Reliability

LLM output is validated with structured-output expectations, bounded retries, and repair. Invalid or empty JSON must fail closed without leaving partial edits.
