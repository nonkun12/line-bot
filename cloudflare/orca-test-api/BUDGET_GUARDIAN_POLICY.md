# ORCA Budget Guardian — Core Policy

## Purpose
Budget Guardian is a deterministic, fail-closed safety gate separate from task-generating agents. This increment evaluates timestamped usage snapshots; it does not poll vendors, call an AI model, dispatch GitHub Actions, or mutate production state.

## Required spend domains
- Cloudflare Workers
- Cloudflare D1
- GitHub Actions

Every required source must provide a current-period snapshot with enabled=true. Missing, disabled, malformed, stale, future-dated, or out-of-period telemetry is BLOCKED. Telemetry cannot disable its own budget check. A trusted operator-disable control is not implemented in this increment.

## Internal thresholds
- 70%: WARN; continue only with fresh telemetry.
- 80%: SUPPRESS new tasks and Actions dispatch.
- 90% or higher: STOP new work; both task registration and Actions dispatch must be rejected by every execution entry point.
- Three consecutive monitor/collection failures: BLOCKED/HOLD.
- Unknown usage or unknown configured limit: BLOCKED.

These are conservative ORCA policy thresholds, not vendor quota guarantees. Limits must come from verified current account/plan data. Never hard-code an assumed GitHub minutes allowance or assume a vendor free tier is available to this account.

## Independent controls
- Global HOLD must be positively confirmed clear (value=off); missing or unavailable state blocks.
- Budget Guardian cannot release Global HOLD, Recovery HOLD, or its own BLOCKED state.
- No automatic paid API, paid Cloudflare plan, paid runner, overage, or cloud-model fallback.
- No AI inference is required for the safety decision. Any future AI component may explain findings only and cannot override the deterministic gate.
- The monitor must not start tasks or dispatch Actions. It may only report and set a restrictive state through an explicitly authorized control path.
- Do not activate scheduling, apply D1 migrations, configure secrets, deploy, or change production settings as part of this core PR.

## Snapshot contract
Each enabled source snapshot contains name, explicit enabled boolean, used and positive verified limit in the same unit, and ISO timestamps observed_at, period_start, period_end.

Snapshots older than 90 minutes, more than five minutes in the future, or outside the current period are BLOCKED. All required sources must be supplied. The evaluator is pure and performs no network access.

## Scope and remaining work
This PR adds the deterministic evaluator and unit tests only. Vendor-specific usage collectors, durable state/ledger, notifications, and integration with every ORCA execution gate remain separate work. Unit tests verify the evaluator returns STOP and both allow flags false at 90% and above, but do not prove that live task-registration or Actions-dispatch entry points are wired to this evaluator. Until those integration tests exist, real stop behavior remains unverified. Until implemented, verified, and explicitly activated, this code is not a live budget monitor.
