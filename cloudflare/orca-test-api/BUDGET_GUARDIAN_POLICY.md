# ORCA Budget Guardian — Core Policy

## Purpose
Budget Guardian is a deterministic, fail-closed evaluator. This increment evaluates timestamped usage snapshots only; it does not poll vendors, call an AI model, dispatch GitHub Actions, or mutate production state.

## Required spend domains
- Cloudflare Workers
- Cloudflare D1
- Cloudflare Durable Objects

Every required source must provide a current-period snapshot with an explicit `enabled: true`. Missing, disabled, malformed, stale, future-dated, or out-of-period telemetry is BLOCKED. Telemetry is not allowed to disable its own spend-domain control. There is no operator-disable bypass in this increment; adding one requires a separately authenticated, audited control plane.

## Internal thresholds
- Below 70%: CLEAR; continue only with fresh telemetry.
- 70%: WARN; continue only with fresh telemetry.
- 80%: SUPPRESS new tasks and Actions dispatch.
- 90% or higher: STOP new tasks and Actions dispatch.
- Three consecutive monitor/collection failures: BLOCKED/HOLD.
- Unknown usage or unknown configured limit: BLOCKED.

These are conservative ORCA policy thresholds, not vendor quota guarantees. Limits must come from verified current account/plan data. For each Cloudflare domain, the collector must normalize the highest utilization among that domain's independently limited dimensions (for example requests, rows, storage, or duration) to a single percentage before publishing the snapshot. It must not treat one dimension as a proxy for all others.

`nonkun12/line-bot` is confirmed public. GitHub documents standard GitHub-hosted runners as free and unlimited for public repositories, so GitHub Actions minutes are not a finite free-tier budget source for this repository. Larger runners remain excluded because they can be charged. GitHub artifact storage is a separate account-level allowance shared with GitHub Packages; it is not represented by this evaluator until complete account-wide usage and limit telemetry is available.

## Independent controls
- Global HOLD must be positively confirmed clear (value=off); missing or unavailable state blocks.
- Budget Guardian cannot release Global HOLD, Recovery HOLD, or its own BLOCKED state.
- No automatic paid API, paid Cloudflare plan, paid runner, overage, or cloud-model fallback.
- No AI inference is required for the safety decision. Any future AI component may explain findings only and cannot override the deterministic gate.
- The evaluator's `allowNewTasks` and `allowActionsDispatch` outputs are decisions, not proof that every production entry point enforces them.
- This increment adds a D1-backed `budget_guard_state` admission gate to the Worker `POST /tasks`, `POST /tasks/:id/approve`, and `POST /tasks/:id/claim` paths. Each write repeats the gate predicate inside its SQL mutation. Only a fresh `CLEAR` or `WARN` state admits work; missing, stale, `SUPPRESS`, `STOP`, `BLOCKED`, or latched STOP state rejects it. The migration seeds the state as BLOCKED.
- A read-only `GET /control/loop-admission` preflight endpoint now combines the authoritative Durable Object Global HOLD state with the D1 Budget Guardian admission state. It requires the separate `ORCA_LOOP_PREFLIGHT_TOKEN` credential and returns 200 only when both controls explicitly allow; otherwise it returns 423. It does not write state or collect usage telemetry. Draft workflow integration is tracked separately in PR #1345; this endpoint alone does not activate scheduled execution.
- The state writer, vendor telemetry collectors, authenticated human release workflow, and GitHub Actions dispatch gate are NOT implemented in this increment. Until a trusted monitor populates the D1 state and the Actions path is separately gated, this is an isolated admission-gate integration, not an active production budget monitor or complete Actions stop switch.
- Do not activate scheduling, apply D1 migrations to a remote database, configure secrets, deploy, or change production settings as part of this PR.

## Workers Free quota reference (verify against the live account before activation)

The following documented Workers Free limits are the initial reference only. The collector must verify the actual account plan and current limits; it must not silently substitute these values if the account's plan or limits differ.

| Domain | Metered dimensions to monitor | Documented Workers Free allowance |
|---|---|---|
| Workers | Inbound requests per UTC day | 100,000/day |
| Workers | CPU time per invocation | 10 ms/invocation (hard per-invocation limit, not a daily pool) |
| D1 | Rows read per UTC day | 5,000,000/day |
| D1 | Rows written per UTC day | 100,000/day |
| D1 | Total storage | 5 GB |
| Durable Objects (SQLite) | Requests per UTC day | 100,000/day |
| Durable Objects (SQLite) | Compute duration per UTC day | 13,000 GB-s/day |
| Durable Objects (SQLite) | Rows read / written per UTC day | 5,000,000 / 100,000 per day |
| Durable Objects (SQLite) | Total storage | 5 GB |

References: [Workers limits](https://developers.cloudflare.com/workers/platform/limits/), [D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/), [D1 metrics and analytics](https://developers.cloudflare.com/d1/observability/metrics-analytics/), and [Durable Objects pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/).

D1 GraphQL datasets include `d1AnalyticsAdaptiveGroups` and `d1StorageAdaptiveGroups`, with a 31-day retention window. However, D1 analytics records requests only when SQL execution is reached; failures before SQL execution are absent. Per-query Workers Binding metadata provides precise row counts, but account-wide totals require complete coverage of every D1 database. The collector must validate account-wide coverage, the current UTC-day window, and the source watermark before publishing a usable snapshot. Missing or delayed coverage remains BLOCKED.

The 15-second live admission watcher also consumes quota: at most one Worker request, one Durable Object request, and a small D1 state read per poll. At 160 polls in a 40-minute run, that is up to 160 requests in each request-metered domain and 160 D1 row reads per run. The collector must include guardian overhead in account-wide totals rather than treating monitoring as free of quota impact.

## Snapshot contract
Each required source snapshot contains name, explicit `enabled: true`, used and positive verified limit in the same unit, and ISO timestamps `observed_at`, `period_start`, `period_end`.

Snapshots older than 10 minutes, more than five minutes in the future, or outside the current period are BLOCKED. All required sources must be supplied. A collector's poll timestamp alone does not prove that vendor analytics are current: live integration must also verify the source data's coverage/watermark and block if the provider has not reported through a sufficiently recent time. The evaluator is pure and performs no network access.

## Scope and remaining work
This PR hardens the pure evaluator and expands deterministic unit tests, including 90% and above stop decisions for each spend domain. It does not yet connect a verified live usage collector or enforce the decision at every task-registration and Actions-dispatch entry point. Therefore a passing unit test is not proof that live work actually stops at 90%. Vendor-specific collectors for Workers, D1, and Durable Objects, authenticated telemetry, source-data freshness/watermark validation, durable state/ledger, race-safe execution gating, notifications, and integration with every ORCA execution gate remain separate work. Until those pieces are implemented, verified, and explicitly activated, this code is not a live budget monitor.
