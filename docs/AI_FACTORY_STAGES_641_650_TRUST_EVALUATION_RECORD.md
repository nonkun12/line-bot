# AI Factory Stages 641–650: Trust Evaluation Record

| Stage | Responsibility |
|---|---|
| 641 | Bind the subject, attestation chain, evaluator, and evaluation identity |
| 642 | Bind the exact policy version used for the declared evaluation |
| 643 | Declare accepted/rejected/indeterminate/revoked outcomes |
| 644 | Restrict evaluation to an explicit, non-wildcard resource and claim scope |
| 645 | Require exact attestation evidence coverage and a declared manifest digest |
| 646 | Record exceptions, owners, states, and resolution evidence |
| 647 | Record conflict-of-interest check declarations |
| 648 | Bound the evaluation by an explicit validity window and renewal requirement |
| 649 | Bind the immutable audit-record reference and creation/evaluation times |
| 650 | Integrate a fail-closed trust-evaluation review gate |

## Trust boundary

All inputs are caller-supplied declarations. This module does not cryptographically
verify the attestation chain, authenticate evaluators, execute policy semantics, check
conflicts independently, query live revocation services, or establish the truth of a
trust decision. Even TRUST_ACCEPTED_DECLARED grants no trust, permission, or release
authorization. READY_FOR_INDEPENDENT_REVIEW means structural completeness only.
