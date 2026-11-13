# GitHub-native 30-minute LOOP migration (Phase 1)

## Scope

This phase adds a Cloudflare-independent verifier contract for GitHub Actions
budget evidence. It does **not** change the existing main workflow, enable a
schedule, dispatch a worker, alter secrets, or release Global HOLD.

The existing Cloudflare-backed PRs remain proposals only. Do not merge them
wholesale into this migration.

## Evidence contract

The verifier in scripts/orca_github_native_budget_evidence.py accepts exactly
one source: github_actions. Cloudflare Workers, D1, and Durable Objects are not
required or accepted. The signed envelope is bound to the repository and
billing account, and includes a current billing period, exact usage counter,
verified included-minute limit, complete resource coverage, and fresh source
watermark.

The HMAC key must be held only by an independently operated trusted collector.
A GitHub Actions job or task worker must never create or sign its own evidence.
The collector must obtain both usage and the included-minute limit from
authoritative account-level sources and account for every billable runner.
A repository-local environment variable, a workflow input, a self-reported
remaining_minutes value, or a test fixture is not authoritative evidence.

## Important current blocker

No trusted GitHub Actions quota collector has been implemented or connected.
The verifier and fixtures define the acceptance contract only. Until a trusted
collector is independently deployed and its account-wide coverage and plan
limit are verified, the 30-minute LOOP must remain **BLOCKED**.

GitHub Actions concurrency, timeout-minutes, and a per-run task cap are
additional deterministic guardrails; they do not prove remaining free quota.
Do not infer quota availability from recent successful runs or from a usage
counter without a verified plan limit.

## Next phases

1. Implement and independently validate the account-level collector.
2. Add a GitHub-native task queue/claim implementation with atomic claim and
   lease-expiry tests. GitHub Issues alone are not an atomic queue.
3. Add a common LINE identity + task-bound approval verifier.
4. Add a latched GitHub-native Global HOLD. Missing/unreadable state blocks.
5. Wire a single serialized workflow only after all preceding evidence exists.
6. Run read-only, local contract, concurrency, replay, and failure-injection
   tests before any one-task canary. Keep auto-patch and auto-deploy disabled.

## Safety invariants

- Existing main and the legacy LOOP remain untouched.
- No Cloudflare resource, secret, database, or Worker is deleted or modified.
- No scheduled execution or workflow dispatch is enabled by this phase.
- Missing, stale, partial, unsigned, or mismatched evidence blocks execution.
- No automatic merge, deployment, or Global HOLD release.
