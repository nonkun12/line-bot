# ORCA Budget Guardian — Core Policy

## Purpose
Budget Guardian is a deterministic, fail-closed evaluator. This increment evaluates timestamped usage snapshots only; it does not poll vendors, call an AI model, dispatch GitHub Actions, or mutate production state.

## Required spend domains
- Cloudflare Workers
- Cloudflare D1
- GitHub Actions

Every required source must provide a current-period snapshot with an explicit `enabled: true`. Missing, disabled, malformed, stale, future-dated, or out-of-period telemetry is BLOCKED. Telemetry is not allowed to disable its own spend-domain control. There is no operator-disable bypass in this increment; adding one requires a separately authenticated, audited control plane.

## Internal thresholds
- Below 70%: CLEAR; continue only with fresh telemetry.
- 70%: WARN; continue only with fresh telemetry.
- 80%: SUPPRESS new tasks and Actions dispatch.
- 90% or higher: STOP new tasks and Actions dispatch.
- Three consecutive monitor/collection failures: BLOCKED/HOLD.
- Unknown usage or unknown configured limit: BLOCKED.

These are conservative ORCA policy thresholds, not vendor quota guarantees. Limits must come from verified current account/plan data. Never hard-code an assumed GitHub minutes allowance or assume a vendor free tier is available to this account.

## Independent controls
- Global HOLD must be positively confirmed clear (value=off); missing or unavailable state blocks.
- Budget Guardian cannot release Global HOLD, Recovery HOLD, or its own BLOCKED state.
- No automatic paid API, paid Cloudflare plan, paid runner, overage, or cloud-model fallback.
- No AI inference is required for the safety decision. Any future AI component may explain findings only and cannot override the deterministic gate.
- The evaluator's `allowNewTasks` and `allowActionsDispatch` outputs are decisions, not proof that production entry points enforce them.
- Do not activate scheduling, apply D1 migrations, configure secrets, deploy, or change production settings as part of this PR.

## Snapshot contract
Each required source snapshot contains name, explicit `enabled: true`, used and positive verified limit in the same unit, and ISO timestamps `observed_at`, `period_start`, `period_end`.

Snapshots older than 90 minutes, more than five minutes in the future, or outside the current period are BLOCKED. All required sources must be supplied. The evaluator is pure and performs no network access.

## Scope and remaining work
This PR hardens the pure evaluator and expands deterministic unit tests, including 90% and above stop decisions for each spend domain. It does not yet connect a verified live usage collector or enforce the decision at every task-registration and Actions-dispatch entry point. Therefore a passing unit test is not proof that live work actually stops at 90%. Vendor-specific collectors, authenticated telemetry, durable state/ledger, race-safe execution gating, notifications, and integration with every ORCA execution gate remain separate work. Until those pieces are implemented, verified, and explicitly activated, this code is not a live budget monitor.
