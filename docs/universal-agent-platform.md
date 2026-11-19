# Universal Agent / Project Platform

## Goal

LINE AI Secretary is both a user-facing secretary and a reusable AI work platform. It must be able to improve itself, create new software projects, maintain existing projects, and perform non-software tasks without mixing repositories or changing `line-bot` unintentionally.

## Repository ownership rules

- `nonkun12/line-bot` is the canonical repository for the AI Secretary platform itself.
- One independently deliverable software product gets one dedicated GitHub repository.
- Render, OCI, n8n, and other runtime services are deployment/operation environments, not the canonical source of truth.
- New-project generation must never write product code into `line-bot` unless the request explicitly targets the Secretary platform itself.

## Request classes

### 1. Self-improvement

Examples:

- `自分自身を改善して`
- `自分の問題点を調べて改善案を作って`
- `line-botのテスト不足を改善して`

Target: `nonkun12/line-bot`.

Required flow: inspect -> propose -> implement on branch -> test -> review -> repair if needed -> PR -> merge gate -> deploy gate -> post-deploy verification.

### 2. New software project

Examples:

- `開発: TODO管理Webアプリを作って`
- `開発: 顧客管理システムを作って`
- `開発: 新しい○○ソフトを作って`

Target: a newly created dedicated GitHub repository selected from a safe project slug. The generated project must have its own source tree, tests, CI, README, and deployment definition when appropriate.

Required flow: understand requirements -> architect -> create repository -> implement -> test -> review -> repair -> PR -> merge gate -> deploy gate -> report location.

### 3. Existing software maintenance

Examples:

- `ai-todo-appを改良して`
- `○○のバグを直して`

Target: the explicitly selected repository. Never silently fall back to `line-bot`.

### 4. Non-software work

The platform must also support work products that are not code, including research, analysis, reports, documents, data processing, monitoring, operational checks, planning, and content generation.

These tasks should use task-appropriate agents and artifact storage rather than forcing a GitHub code change. When a durable artifact is needed, use an explicit artifact/project destination and retain provenance.

## Agent platform

Agents are first-class resources. The system must support both registering fixed agents and safely creating/configuring new agents when a task requires a capability that does not exist.

Agent categories include, but are not limited to:

- Management / orchestration
- Architect / planner
- Implementer
- Tester / QA
- Reviewer
- Debugger / Repairer
- Refactorer
- Integrator / release manager
- GitHub / repository management
- Deployment / operations
- Research / web research
- Data analysis
- Reporting / document generation
- Monitoring / incident response
- English learning
- Stocks / market data
- AI news
- Voice / speaker

An agent created by the platform must have an explicit name, purpose, input/output contract, allowed tools, resource scope, safety policy, tests, and registration metadata. Agent creation itself is a governed change and must pass validation before being enabled.

## Generic execution pipeline

```text
Request
  -> Manager
  -> Task classifier
  -> Project / repository resolver
  -> Agent planner
  -> Specialist agents
  -> Test / validation
  -> Review
  -> Repair loop (bounded)
  -> Integration
  -> Artifact / PR / deployment
  -> Verification
  -> User report
```

Not every request needs every stage. The manager should select the smallest safe pipeline that satisfies the task.

## AI self-improvement loop

The Secretary should be able to inspect its own code, runtime errors, test failures, performance signals, and user-visible defects; propose improvements; implement them through a branch; validate them; and produce a reviewable PR. Direct writes to `main` are prohibited for autonomous changes.

Self-improvement must not weaken its own safety gates, authentication, secrets handling, repository protections, or auditability without a separate explicit approval path.

## Structured outputs and failure handling

LLM responses used as machine-readable plans must use structured-output validation. Invalid or empty output must trigger bounded retry/repair with clear diagnostics rather than an unhandled `JSONDecodeError`. A failed model response must fail closed and restore any partial working-tree changes.

## Project registry

Introduce a durable project registry that maps:

- project name
- repository name/URL
- project type
- primary runtime/deployment target
- owner/user scope
- active branch
- status
- last known successful commit
- supported agents

This registry is the routing authority for future maintenance requests.

## Security boundaries

- Secrets stay in GitHub/Render/OCI secret stores and are never committed.
- Repository writes are scoped to the resolved project.
- Autonomous operations use branches and pull requests.
- New repositories and newly generated agents are auditable.
- Production deployment is a separate gate from code generation.
- Bounded retries prevent runaway loops and API abuse.

## Acceptance examples

1. `自分自身を改善して` changes only `nonkun12/line-bot` through a governed PR.
2. `開発: TODO管理Webアプリを作って` creates `nonkun12/<safe-slug>` and does not modify `line-bot`.
3. `ai-todo-appを改良して` routes to that repository.
4. `このエラーを調べてレポートして` produces a report without forcing a code PR.
5. `新しいAgentを作って株価監視ができるようにして` creates and validates a new agent definition and then uses it under the same safety gates.
