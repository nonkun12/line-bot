# Recovery AI: local Apple Foundation Model advisor

This is an **optional Mac-only diagnostic helper** for the Recovery AI workflow.
It calls Apple's `fm respond` CLI, which uses the on-device system model.

## Safety boundaries

- It accepts task ID, failure category, and failing-test identifiers only; do not pass raw logs, prompts, tracebacks, or secrets.
- It validates a strict JSON response schema and applies a 20-second default timeout (maximum 60 seconds).
- It never executes model suggestions, changes files, applies patches, merges pull requests, or deploys.
- Errors do not include the model's stdout/stderr, to avoid leaking sensitive output.
- On non-macOS hosts, it stops with an explicit error. The hosted GitHub Actions loop must skip this adapter; it cannot access a Mac's on-device model.
- Existing Recovery AI and distributed-loop behavior is unchanged. Keep `AUTO_APPLY_PATCH=false` and `AUTO_DEPLOY=false`.

## Use on a Mac

From the repository root, call it from Python with a task identifier, allowlisted failure category, and test identifiers:

```python
from scripts.recovery_ai_fm_advisor import diagnose

suggestion = diagnose(
    task_id="example-task",
    category="test_regression",
    failing_tests=["tests/test_example.py::test_expected_behavior"],
)
print(suggestion)
```

The Mac must have the `fm` CLI installed and report the system model as available. This module deliberately does not integrate itself into the hosted loop or automatically apply advice. A later integration should store the suggestion as untrusted advisory metadata and preserve the existing deterministic safety gates.
