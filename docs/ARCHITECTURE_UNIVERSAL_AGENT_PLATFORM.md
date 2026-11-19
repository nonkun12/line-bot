# Universal AI Agent Platform Architecture

## Goal

Evolve `nonkun12/line-bot` into a governed platform that can:

- safely improve the AI Secretary itself;
- create independent software projects;
- maintain registered existing software;
- create and validate new Agents;
- execute non-software work such as research, analysis, reporting, documents, monitoring, and operations.

## System boundary

```text
LINE / Slack / API
       |
       v
Channel Adapter
       |
       v
AI Secretary Core
       |
       v
Manager
       |
       +--> Classifier
       |       |
       |       v
       |   Project / Artifact Resolver
       |       |
       |       v
       |     Planner
       |       |
       +-------+----------------------+
               |
               v
       Specialist Agents
               |
               v
       Test / Validation
               |
               v
             Review
               |
        bounded Repair loop
               |
               v
          Integration
               |
      +--------+---------+
      |        |         |
      v        v         v
    GitHub  Artifacts   Deploy/Ops
      |        |         |
      +--------+---------+
               |
               v
          Verification
               |
               v
             Report
```

The channel layer is not allowed to choose arbitrary repositories or bypass governance.

## Core components

### Manager

Coordinates the request lifecycle and selects the minimum safe pipeline.

### Classifier

Determines a governed work mode: `self_improvement`, `new_software`, `existing_software`, `agent_management`, `non_software`, or `normal`.

Explicit forms are classified deterministically. Ambiguous work must not silently become repository-changing work.

### Project / Artifact Resolver

Uses the Project Registry for existing software. Unknown projects fail closed. New software is represented as a request for repository creation rather than a fallback to `line-bot`.

### Planner

Creates a side-effect-free stage plan. Execution adapters are added later.

### Specialist Agents

Perform bounded tasks under an Agent contract. They do not select arbitrary repositories or bypass gates.

## Project Registry

Canonical software routing fields:

- project name;
- GitHub repository;
- project type;
- runtime target;
- owner scope;
- active branch;
- status;
- last successful commit;
- supported Agents.

`nonkun12/line-bot` is the AI Secretary project and self-improvement target.

Independent products use separate repositories:

```text
nonkun12/line-bot
nonkun12/ai-todo-app
nonkun12/ai-customer-app
nonkun12/<future-project>
```

GitHub is the canonical source of truth. Render, OCI, and n8n are runtime/orchestration infrastructure.

## Agent Registry

Executable Agent routing and Agent governance metadata are separate layers.

Lifecycle:

```text
Generate -> Validate -> Test -> Review -> Enable
```

An Agent specification must declare its name, purpose, input/output contract, allowed tools, resource scope, safety constraints, validation tests, lifecycle state, and registration metadata.

An Agent must not become `enabled` without passing the preceding lifecycle gates.

## Execution modes

### Self-improvement

```text
Inspect -> Plan -> Implement -> Test -> Review -> Repair
-> Integrate -> PR -> Merge Gate -> Deploy Gate
-> Post-deploy Verification -> Report
```

Self-improvement is stricter than ordinary development. Authentication, secrets, security controls, autonomous-development workflows, routing, merge gates, and deployment gates are protected surfaces. Changes to those areas require explicit approval and are never auto-enabled solely because tests pass.

### New software

```text
Requirements -> Project Classification -> Repository Naming
-> Repository Creation -> Architecture -> Implementation -> QA
-> Review -> Repair -> Integration -> PR -> Merge Gate
-> Deploy -> Verification -> Report
```

New software must not modify `line-bot`.

### Existing software

```text
Resolve registered project -> Inspect -> Plan -> Implement
-> Test -> Review -> Repair -> Integrate -> PR
-> Merge Gate -> Deploy Gate -> Verify -> Report
```

Unknown targets are rejected; they are not guessed.

### Agent creation / upgrade

```text
Requirements -> Generate -> Validate -> Test -> Review -> Enable -> Report
```

### Non-software work

```text
Requirements -> Research / Process -> Validate -> Review
-> Artifact -> Report
```

No GitHub code change is required unless the task explicitly produces software.

## Safety invariants

1. Autonomous repository writes are scoped to a resolved project.
2. New software has its own repository.
3. Self-improvement never writes directly to `main`.
4. Merge and deployment remain separate gates.
5. Secrets are never committed.
6. Generated Agents cannot enable themselves without validation and review.
7. Repair/retry loops are bounded.
8. Invalid model output fails closed.
9. Failed generation restores partial working-tree changes.
10. Changes to security and control-plane surfaces require explicit approval.

## LLM reliability

Machine-actionable model output must pass parsing and schema validation before execution.

```text
LLM -> Parse -> Schema Validate
                 |
        invalid -> bounded retry/repair
                 |
          still invalid -> fail closed
                 |
              valid
                 v
             Execute
```

Unchecked `json.loads()` is not a sufficient control boundary.

## Provider adapters

The core pipeline remains provider-neutral. Later adapters may implement GitHub repository creation, branches, pull requests, merge gates, artifact storage, deployment, and external research/data providers without changing the Manager/Classifer/Resolver/Planner contracts.
