# Recovery AI: local Apple Foundation Model advisor

This is an **optional Mac-only diagnostic helper** for Recovery AI. It calls Apple's
`fm respond` CLI for on-device diagnostic suggestions.

## Safe integration boundary

- `scripts/recovery_ai.py` remains the authoritative deterministic controller.
- `scripts/recovery_ai_local_advisor.py` is an explicit, opt-in bridge. It asks fm
  only when the supplied decision is `REPAIR_ONCE` and the category is allowlisted
  (`test_regression`, `timeout`, or `process_crash`).
- `HOLD`, `STOP_FAIL_CLOSED`, `RETRY`, security violations, invalid evidence, and
  other categories skip diagnosis.
- The result is marked `ADVISORY_ONLY`; it is not a repair instruction. It does not
  persist state, execute commands, edit files, apply patches, merge, or deploy.
- Adapter failures or invalid output produce `UNAVAILABLE` without changing the
  original RecoveryDecision.
- Never pass raw logs, prompts, tracebacks, or secrets; provide identifiers only.
- The hosted distributed loop must not invoke this Mac-only adapter. Keep
  `AUTO_APPLY_PATCH=false` and `AUTO_DEPLOY=false`.

## Opt-in use on a Mac

```python
from scripts.recovery_ai_local_advisor import advise_for_decision

result = advise_for_decision(
    decision,  # RecoveryDecision already returned by the deterministic controller
    category="test_regression",
    failing_tests=["tests/test_example.py::test_expected_behavior"],
)
# Review result only when result.status == "ADVISORY_ONLY".
print(result)
```

The bridge is deliberately not wired into the hosted loop. It requires an explicit
caller on a Mac, and advice must be independently reviewed before any repair work.
