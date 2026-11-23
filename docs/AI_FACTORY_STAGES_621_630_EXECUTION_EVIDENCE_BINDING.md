# AI Factory Stages 621–630: Execution Evidence Binding

| Stage | Responsibility |
|---|---|
| 621 | Bind experiment and protocol identity |
| 622 | Declare execution envelope: environment, command, input manifest, timeout, memory, CPU, and network policy |
| 623 | Bind result artifact references, declared SHA-256 strings, media types, and sizes |
| 624 | Record declared outcomes with start/finish timestamps |
| 625 | Record failure events and reasons |
| 626 | Record abort events and reasons |
| 627 | Bind output schema and declared validation coverage |
| 628 | Bind benchmark protocol and sample/population coverage |
| 629 | Declare uncertainty interval/method and baseline comparison |
| 630 | Integrate checks into a fail-closed evidence gate |

## Trust boundary

All values are caller-supplied declarations. This module does not execute workloads,
read artifact bytes, verify hashes, enforce CPU/memory/time/network limits, execute schema
validation, establish representative sampling, recompute confidence intervals, or rerun
baseline comparisons. A syntactically valid SHA-256 declaration is not a verified digest.

READY_FOR_INDEPENDENT_REVIEW means only that supplied metadata passed structural checks.
It is not evidence that an experiment ran, results are valid, or capability improved.
Execution, automatic execution, and release remain unauthorized.
