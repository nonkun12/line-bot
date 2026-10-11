# Apple Foundation Models advisor (local-only, phase 1)

This optional adapter calls the Mac-local `fm respond` CLI for a short diagnostic
suggestion. It is not required for the distributed loop and is not invoked by GitHub
Actions or the production workflow.

## Safety boundary

- The model receives only a task ID, an allowlisted failure category, and bounded test identifiers.
- The adapter passes a minimal environment; API keys and application secrets are not forwarded.
- Execution has a hard timeout and bounded output. Missing CLI, errors, timeout, or malformed output produce no advice.
- Output is advisory text only. It cannot decide PASS/FAIL, retry, hold/resume, execute commands, apply patches, merge, or deploy.
- Existing deterministic Recovery AI and Safety Gate remain authoritative.
- Keep the service bound to the Mac/local user session. Do not expose it on the network.
- A Mac-off run must proceed without this advisor; do not queue untrusted model output for later execution.

## Local Qwen vs Apple model comparison

After confirming both CLIs are available on the Mac, run from the repository root:

```bash
python3 scripts/compare_local_models.py
```

The script uses three synthetic software-diagnostic scenarios, sends the same prompt to
`fm respond` and `ollama run qwen2.5-coder:7b`, applies a 60-second timeout per response,
and writes results to `artifacts/local-ai-benchmark.json`. It does not read repository
files, invoke model-suggested commands, modify code, or contact a cloud model API.
Review answer quality against each case's rubric as well as elapsed time; speed alone
does not prove higher quality or faster real recovery. Do not commit the generated
results file if it contains anything other than the synthetic benchmark data.

## Validation status

The adapter is mock-testable on CI without Apple hardware. Before enabling any caller,
run focused and full test suites, then conduct a manual Mac smoke test with the installed
`fm` CLI. The comparison script is a local measurement harness, not a CI benchmark.
This phase intentionally does not connect the adapter to the live loop or claim improved
recovery time.
