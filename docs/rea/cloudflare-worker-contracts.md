# REA Cloudflare / D1 / LINE inspection contract

REA scans the explicit allowlist in scripts/rea_readonly_scanner.py, including
cloudflare/, root config.py, and the existing Python/JS/SQL/HTML/JSON/YAML
areas. A COMPLETE result means every supported tracked file in that allowlist
was read; it does NOT mean the entire repository or a deployed service was
verified. Excluded paths remain outside coverage.

## Static checks

- Cloudflare ORCA Worker: presence of constant-time comparison, API-token
  authorization, D1 batch operations, append-only nonce ledger, owner-scoped
  status header, claim-token completion, notification outbox, and Web Crypto
  HMAC primitives.
- D1 migrations: nonce primary key, unique approval identity, task foreign
  key, and outbox primary key.
- LINE task-status client: verified submitter identity is sent in
  X-ORCA-Task-Owner, not as a URL query parameter.
- Existing checks: Python/JSON syntax, dangerous workflow flags, broad
  permissions: write-all, clean worktree and index state, unsupported-file
  and oversized-file coverage accounting.

These are static source-contract checks. They do not prove JavaScript syntax,
SQL migration correctness on Cloudflare D1, transaction isolation under real
concurrency, HMAC interoperability in a deployed Worker, LINE webhook
authenticity, or notification delivery. Those remain UNVERIFIED until
isolated integration tests and deployed-runtime evidence exist.

## Evidence workflow

.github/workflows/rea-readonly-evidence.yml runs against the exact PR head
SHA, tests the scanner, emits a SHA-bound JSON report, and uploads the report
as a workflow artifact. The workflow is evidence-only and intentionally does
not enforce branch protection or authorize any action. Findings are review
items, not approvals.

REA remains read-only: no project-code execution, task execution, patching,
approval, HOLD release, merge, deployment, secret access, or schedule changes.
