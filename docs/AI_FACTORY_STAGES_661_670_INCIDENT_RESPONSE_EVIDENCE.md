# AI Factory Stages 661–670: Incident Response Evidence

| Stage | Responsibility |
|---|---|
| 661 | Bind incident, subject, and triggering monitor events |
| 662 | Declare severity, triage state, scope, and rationale |
| 663 | Preserve an ordered incident timeline |
| 664 | Record a response decision and explicit human-approval requirement |
| 665 | Define bounded response actions, owners, targets, and execution states |
| 666 | Declare approval records and separation-of-duties constraints |
| 667 | Bind execution-state declarations to evidence references |
| 668 | Require a rollback/recovery plan without executing it |
| 669 | Require an independent verification plan and closure evidence |
| 670 | Integrate a fail-closed incident-response review gate |

## Trust and execution boundary

All fields are caller-supplied declarations. This module does not detect incidents,
authenticate approvers or executors, authorize actions, perform containment or
remediation, execute rollback, run verification, or close incidents operationally.
A complete record is only structurally ready for independent review. Human approval
is required by declaration; the approval itself is not authenticated.
