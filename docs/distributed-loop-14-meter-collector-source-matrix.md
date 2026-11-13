# 30-minute LOOP budget collector source matrix

## Decision

**The 30-minute LOOP remains BLOCKED.** No currently verified source combination provides all 14 schema-v2 meters with complete account coverage, exact counter semantics, authoritative limits, and a source watermark no older than ten minutes.

Do not replace missing evidence with estimates, account-level billing totals, poll timestamps, self-asserted `exact` flags, or synthetic counters. A signed payload proves who produced a payload; it does not make an inexact or delayed source authoritative.

## Meter-by-meter source assessment

| Meter ID | Candidate source | What it actually provides | Enforcement decision |
|---|---|---|---|
| `cloudflare.workers.requests.daily` | Workers GraphQL metrics | Per-Worker metrics; recent graph intervals can have aggregation/delivery drop-off | BLOCKED until account-wide exact coverage and watermark are independently established |
| `cloudflare.workers.cpu_ms_per_invocation.max` | Workers CPU metrics | Quantiles based on reservoir sampling; not a guaranteed exact maximum for every invocation | BLOCKED; sampled quantiles cannot prove a hard maximum |
| `cloudflare.workers_logs.events.daily` | Workers Logs analytics | Analytics/observability data, not yet proven as a complete account-wide billable counter with a <=10m watermark | BLOCKED |
| `cloudflare.d1.rows_read.daily` | D1 analytics / Cloudflare billable usage | Billable Usage v2 is daily-grain and restricted/alpha; not a live ten-minute counter | BLOCKED |
| `cloudflare.d1.rows_written.daily` | D1 analytics / Cloudflare billable usage | Same daily-grain limitation; no verified live account-wide exact source | BLOCKED |
| `cloudflare.d1.storage_bytes.total` | D1 database metadata / billable usage | Per-database metadata may help inventory, but complete account-wide current storage and authoritative limit have not been proven | BLOCKED |
| `cloudflare.durable_objects.requests.daily` | Durable Objects analytics / billable usage | No verified exact account-wide live counter and complete namespace inventory | BLOCKED |
| `cloudflare.durable_objects.duration_gb_seconds.daily` | Durable Objects analytics / billable usage | Usage is wall-clock active duration; no verified exact live account-wide source | BLOCKED |
| `cloudflare.durable_objects.sqlite_rows_read.daily` | Durable Objects SQLite usage / billable usage | Billable Usage v2 is daily-grain; no verified live exact counter | BLOCKED |
| `cloudflare.durable_objects.sqlite_rows_written.daily` | Durable Objects SQLite usage / billable usage | Same daily-grain limitation | BLOCKED |
| `cloudflare.durable_objects.sqlite_storage_bytes.total` | Durable Objects SQLite metadata / billable usage | No verified complete live account-wide total across every SQLite namespace | BLOCKED |
| `github.actions.compute_cost_usd.monthly` | GitHub billing usage report | Account-billed usage summary; report freshness is not guaranteed at <=10m | BLOCKED for the 10m gate until a fresh authoritative source is proven |
| `github.actions_packages.shared_storage_gb_hours.monthly` | GitHub Actions artifact / GitHub Packages billing | Shared pooled allowance; artifact usage updates within 6–12 hours; current size is not accrued GB-hours | BLOCKED |
| `github.actions.cache_storage_gb_hours.monthly` | GitHub Actions cache usage API | Current active cache size, refreshed approximately every five minutes; billing accrues hourly in GB-hours and is a separate per-repository allowance | BLOCKED; current-size samples do not equal accrued monthly GB-hours |

## Verified billing semantics

### Cloudflare

- Workers metrics are per Worker, not automatically an account-wide exact counter.
- Workers request graphs may show a drop-off near the most recent minutes due to aggregation and delivery delay.
- CPU quantiles use reservoir sampling; they cannot certify the exact maximum invocation CPU.
- Cloudflare Billable Usage v2 describes daily records and is restricted/alpha. It is not a ten-minute enforcement feed.
- A collector must separately enumerate every enabled product, Worker, D1 database, and Durable Object namespace. A partial inventory is BLOCKED.

### GitHub Actions

- Public-repository standard GitHub-hosted runners are independently free; larger runners remain billable even for public repositories.
- Private/internal standard runners and cloud sandbox compute can draw from the account's included monthly compute pool. The current repository's public status does not prove zero account-wide compute usage.
- Actions artifacts and GitHub Packages share a storage allowance. Their charges accrue hourly in GB-hours. Artifact storage usage can take 6–12 hours to update.
- Actions cache storage is a separate allowance (10 GB per repository in the documented plan example) and is billed hourly in GB-hours. The cache API refreshes approximately every five minutes but returns current active cache size, not the cumulative GB-hours already accrued.
- A five-minute poll is not enough to reconstruct exact monthly accrued storage: creation/deletion can occur between samples. Do not label sampled integration as exact.

## Required collector architecture before implementation

1. **Inventory first:** enumerate all account products and all relevant resources (Workers, databases, DO namespaces, GitHub repositories and billing scopes). Unknown products or inaccessible pages are BLOCKED.
2. **Source adapter per meter:** every adapter must document its authoritative endpoint, counter semantics, scope, units, period boundaries, freshness SLA, sampling behavior, and limit evidence.
3. **No synthetic freshness:** `observed_at` and `watermark_at` must come from the source. A collector poll time must never replace an older source watermark.
4. **Signed evidence:** HMAC-SHA256 binds the complete schema-v2 payload, account IDs, collector identity, source watermarks, inventory, and all meter records.
5. **Independent evaluation:** the gate validates all 14 meters and computes the worst status. A caller-supplied `status`, `allowed`, or `enforcement_eligible` flag is never authoritative.
6. **Persistent state writer:** only a verified gate decision may update D1. It must aggregate the worst status across all 14 meters, latch STOP at >=90%, and preserve that latch across resets, lower readings, missing telemetry, restarts, and concurrent writes.
7. **Human release:** STOP release requires a separately authenticated human action, a fresh complete snapshot below 80%, and an auditable operator/reason record. A collector or routine scheduled run cannot release it.
8. **In-flight enforcement:** the watcher must stop the active process group and prevent task publication/durable writes when HOLD or budget state becomes unknown, stale, SUPPRESS, STOP, or BLOCKED.
9. **Test before activation:** tests must cover missing/extra/duplicate meters, stale source watermarks, incomplete inventory, HMAC mismatch, STOP persistence, concurrent updates, release authorization, and the 15-second in-flight watcher.

## Activation rule

Until every required meter has a verified source and the signed collector plus persistent D1 writer pass isolated integration tests, the budget endpoint must return BLOCKED. Do not add placeholder secrets, weaken the ten-minute freshness check, or enable the 30-minute schedule.
