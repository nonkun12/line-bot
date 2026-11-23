# AI Factory Stages 426–430: Exception Governance

- **426 — Exception identity and scope:** unique IDs, rationale, requester, and exact bounded scope.
- **427 — Approval separation:** explicit decision reference and requester/approver separation.
- **428 — Lifecycle:** timezone-aware start/expiry window and revocation checks against caller-supplied evaluation time.
- **429 — Scope binding:** exact requested-scope match; wildcard scopes rejected.
- **430 — Aggregate gate:** fail-closed exception governance readiness report.

## Safety and limitations
All fields, actor identities, timestamps, and decision references are caller-supplied declarations. The checks do not authenticate actors, verify approval records, establish authority, or prove that scope is safe. A PASS means only that the declarations satisfy these structural rules at the supplied evaluation time. The result does not activate an exception and never grants execution or promotion authority. No HOLD release, experiments, training, model/weight changes, permission changes, production actions, merge, or deployment. No RSI/ASI claim.
