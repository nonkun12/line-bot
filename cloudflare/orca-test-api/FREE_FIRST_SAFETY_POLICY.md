# ORCA free-first execution safety policy

Status: source policy for review. This file does not activate a scheduler, spend quota,
change Cloudflare account settings, deploy a Worker, or release Global HOLD.

## Cadence

- Distributed-loop scheduler target: every 30 minutes (48 opportunities per UTC day).
- Each tick is a lightweight gate check only. Empty queue means no model startup and no
  GitHub Actions dispatch.
- One scheduler tick may authorize at most four explicitly approved tasks.
- One distributed-loop execution at a time; overlapping ticks are dropped, never queued.
- A missed tick is not replayed as a burst. The next normal tick performs one bounded check.
- The existing `wrangler.toml.example` minutely Cron is for notification-outbox delivery
  (`dispatchOutbox`), not distributed-loop scheduling. Keep it separate so changing loop
  cadence does not silently delay LINE result notifications.

## Independent stop conditions

All conditions are conjunctive. Any missing, stale, malformed, contradictory, or
unavailable signal blocks new work.

1. Global HOLD must be explicitly `off`; initial/missing state is HOLD.
2. Task must have a valid, unexpired, task-bound human approval.
3. Scheduler slot must be unique; one active lease at a time.
4. Per tick: at most four tasks. Per task: 10-minute execution ceiling.
5. Lease is provisional at 15 minutes; expiry does not authorize an automatic retry.
6. Retry at most twice, with exponential backoff. Three consecutive failures engage HOLD.
7. Budget gate must have fresh usage evidence. Unknown usage means BLOCKED.
8. Internal usage policy: 70% warn, 80% suppress new work, 90% hard stop.
   These are conservative policy thresholds, not vendor quota limits.
9. Emergency stop is independent from the scheduler and requires a human release after
   reconciliation. Calendar/month rollover never releases HOLD.

## Free-first budget policy

- Never call paid model APIs or use a paid inference fallback.
- Do not enable Cloudflare Paid, Workers Paid-only products, paid GitHub runners, or
  overage/billing features as an implicit dependency.
- For GitHub Actions, dispatch only for a non-empty, approved queue. The repository is
  public, so standard GitHub-hosted runner minutes have different billing treatment from
  private repositories; still cap dispatches and runtime to prevent runaway execution.
- Calculate Actions internal budget from measured job duration and current account/repo
  policy. Do not hard-code the private-repository 2,000-minute allowance as this repo's
  budget.
- Do not assume a vendor quota counter is available from an API. If a reliable current
  usage signal cannot be read, stop rather than estimate remaining headroom.
- D1 quota ledger is a secondary guard, not a substitute for scheduler, Worker, and
  provider-side controls. A ledger discrepancy or write failure blocks execution.

## Rollout boundary

This policy is not permission to activate the loop. Before enabling a 30-minute scheduler,
the dedicated distributed-loop executor, atomic slot reservation, budget ledger, bounded
Actions dispatch, and deterministic HOLD-race tests must all exist and pass in isolated
tests. Production D1 migrations, secrets, Cloudflare settings, LINE webhook, deployment,
merge, and Global HOLD release require separate explicit approval.
