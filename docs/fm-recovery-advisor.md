# Local `fm` Recovery Advisor — guarded integration

## Purpose

Use Apple's on-device `fm respond` only as an optional, local diagnostic helper after a Mac-side operator or bridge receives a sanitized incident. This is a separate advisor, not a new recovery controller.

## Safety contract

- `scripts/recovery_ai.py` remains the deterministic authority for RETRY, REPAIR_ONCE, HOLD, and STOP_FAIL_CLOSED.
- The advisor accepts only task ID, allowlisted failure category, coarse run status, and test identifiers. It rejects raw logs, prompts, exception messages, unknown fields, and oversized input.
- `fm` is invoked with an argument array (never a shell), a temporary JSON schema, no streaming, and a hard timeout of at most 20 seconds.
- Output is size-limited and schema-validated. Any missing binary, timeout, nonzero exit, malformed output, or validation error returns UNAVAILABLE. Callers must continue safely without the advice.
- The result explicitly carries `authority: none` and `patch_allowed/merge_allowed/deploy_allowed: false`. It cannot change files, execute model-proposed commands, establish PASS, resume held work, merge, or deploy.
- No hosted GitHub Actions job should call this script: `fm` is on the user's Mac, not the ephemeral Linux runner. Do not expose `fm serve` as a network service.

## Manual smoke test (Mac only)

After this branch is reviewed and the test suite passes, a Mac user can pipe a sanitized incident JSON object to the script. The helper itself does not require a new API key or paid service. It requires the existing `fm` CLI and its machine-wide license to have been accepted.

```sh
printf '%s\n' '{"task_id":"smoke-test","category":"test_regression","run_status":"failure","failing_tests":["tests/test_example.py::test_example"]}' | python3 scripts/fm_recovery_advisor.py
```

Expected result: `ADVISORY_ONLY` with a suggested category and read-only checks, or `UNAVAILABLE` if the local model cannot run. Neither result authorizes an action.

## Deliberately not included in this phase

- No call from GitHub Actions, Render, LINE webhook, or Hermes.
- No always-on local server, inbound port, token, automatic repair, or automatic task resume.
- No changes to existing workflow gates, `AUTO_APPLY_PATCH=false`, or `AUTO_DEPLOY=false`.
- A future bridge can enqueue sanitized incidents for user-approved Mac-side processing; that wiring should be a separate reviewed change after this adapter passes tests on GitHub and on the actual Mac.
