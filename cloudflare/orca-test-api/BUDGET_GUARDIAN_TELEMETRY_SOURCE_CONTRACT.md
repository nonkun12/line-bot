# Budget Guardian telemetry source contract

Status: design-only. No collector, credential, deployment, migration, or production activation is included.

## Safety decision

A usage snapshot may authorize work only when it is based on complete, account-wide, current-period, authoritative usage counters for every quota dimension that can independently exhaust the free allowance. A sampled estimate, per-script subset, per-namespace subset, dashboard chart, delayed aggregate, or collector poll timestamp is not sufficient evidence for a 90% hard stop.

If any dimension is sampled, unavailable on the current plan, delayed beyond the freshness window, missing from account-wide coverage, or lacks a verified limit, the source is NOT_ADMISSIBLE and Budget Guardian remains BLOCKED. Do not convert unknown values to zero, extrapolate, interpolate, or infer account usage from this repository's own traffic.

## Source assessment (2026-11-12)

| Meter | Candidate source | What it can support | Hard-stop suitability |
|---|---|---|---|
| Workers requests | Account GraphQL `workersInvocationsAdaptive`; dashboard Worker metrics | Invocation/request diagnostics; per-script or scoped analytics | Not proven exact account-wide billable counter. Adaptive dataset and aggregation lag require explicit sampling/coverage validation. |
| Workers CPU | Worker invocation analytics CPU quantiles | Per-invocation diagnostics/quantiles | Not a complete account-wide daily CPU pool. The Free CPU limit is per invocation, not a daily percentage budget. Enforce per-invocation limits separately. |
| D1 rows read/written | Account GraphQL `d1AnalyticsAdaptiveGroups` / D1 Billable Usage analytics | Account-level daily/month-to-date analytics and diagnostics | Not admissible until the live dataset proves unsampled complete account coverage, watermark freshness, and exact aggregation. SQL-execution analytics may omit failures before SQL execution. |
| D1 storage | `d1StorageAdaptiveGroups` / storage state analytics | Database storage observations | Not admissible until all databases are enumerated and the account-wide maximum/total semantics, freshness, and coverage are proven. |
| Durable Objects requests | `durableObjectsInvocationsAdaptiveGroups` | Namespace invocation diagnostics | Not admissible as exact account-wide billable usage until all namespaces are covered and sampling/lag are proven safe. |
| Durable Objects compute | `durableObjectsPeriodicGroups` (for example, `cpuTime`) | Periodic compute diagnostics | Not admissible until exact billing-unit conversion, all namespaces, completeness, and freshness are verified. |
| Durable Objects storage | `durableObjectsStorageGroups` | Storage observations | Not admissible until every namespace is covered and aggregate semantics are verified. |
| Cloudflare account billable usage API | Billing usage v2 (Alpha/Restricted; documented as deprecated in current API reference) | Billing reconciliation only if account access and returned granularity are confirmed | Do not rely on it for a 30-minute real-time 90% stop. It is not a stable, universally available real-time safety source. |

References:
- Workers metrics and documented aggregation delay: https://developers.cloudflare.com/workers/observability/metrics-and-analytics/
- Workers GraphQL metrics: https://developers.cloudflare.com/analytics/graphql-api/tutorials/querying-workers-metrics/
- GraphQL datasets and adaptive sampling terminology: https://developers.cloudflare.com/analytics/graphql-api/features/data-sets/
- GraphQL API limits and dataset-specific availability: https://developers.cloudflare.com/analytics/graphql-api/limits/
- D1 account billable usage analytics: https://developers.cloudflare.com/d1/observability/billing/
- Durable Objects metrics datasets: https://developers.cloudflare.com/durable-objects/observability/metrics-and-analytics/
- Billing usage API status: https://developers.cloudflare.com/api/resources/billing/

## Required collector output

The collector must produce a signed/authenticated envelope containing:
- schema_version and collector_version;
- account identity (non-secret stable identifier);
- exact quota period start/end and observation timestamp;
- one record for every required meter dimension, including source name, dataset/API, scope, unit, used, verified limit, sampling mode, coverage status, source watermark, and observed_at;
- explicit `complete_account_coverage: true` only after enumerating and reconciling every relevant resource;
- explicit `exact_counter: true` only where vendor documentation and validation establish exactness;
- source errors, pagination status, query window, and raw response digest for audit.

The writer must reject duplicate, missing, unexpected, sampled, partial, stale, future-dated, out-of-period, non-finite, negative, or unverified records. It must never write CLEAR/WARN based only on a successful HTTP response or a fresh poll timestamp.

## Acceptance tests before any live collector can write an admissible state

1. Enumerate all relevant Workers scripts, D1 databases, and Durable Object namespaces for the account; prove pagination is complete.
2. Prove each meter's API value matches Cloudflare's authoritative billable usage for the same period and unit across controlled test intervals.
3. Prove the source is exact, not adaptively sampled, or demonstrate a documented conservative upper-bound that cannot understate usage.
4. Verify data watermark lag remains within the 10-minute freshness window under normal operation and during provider degradation.
5. Test missing resource, partial pagination, GraphQL partial errors, rate limit, auth failure, delayed aggregation, schema drift, reset/day-boundary, and period rollover. Every case must BLOCK.
6. Test 70/80/90% boundaries independently for every meter dimension. 80% suppresses new admissions; 90% latches STOP. No automated release.
7. Include guardian polling and collector overhead in the same account-wide usage totals.
8. Demonstrate that task creation, approval, claim, scheduler dispatch, and in-flight execution all fail closed on stale/unknown state.
9. Human-reviewed release procedure must be separately authenticated, audited, and tested; it must not be part of this collector.

## Current implementation boundary

PR #1344 provides a pure evaluator, D1 admission state seeded BLOCKED, and a read-only preflight route combining authoritative Durable Object Global HOLD with D1 Budget Guardian state. It does not implement a trusted collector or state writer. PR #1345 adds scheduled admission and a live stop watcher but depends on the route and a future trustworthy writer. Neither PR proves that live Cloudflare usage reaches the 90% gate. Do not deploy, migrate remotely, configure secrets, enable schedules, or merge these increments until the source acceptance tests and every enforcement gate pass.
