# AI Factory Stages 631–640: Attestation Chain Declarations

| Stage | Responsibility |
|---|---|
| 631 | Bind the attested subject/package |
| 632 | Declare issuer and signing-key references |
| 633 | Declare signature algorithm and signature reference |
| 634 | Bind an explicit trust-policy version and allowed issuers/algorithms |
| 635 | Bind a revocation snapshot and reject keys declared revoked |
| 636 | Bind trusted-timestamp authority and timestamp evidence declarations |
| 637 | Validate chain sequence and timestamp ordering |
| 638 | Restrict claims to explicit, non-wildcard scope |
| 639 | Bind payload digest declarations and policy version |
| 640 | Integrate checks into a fail-closed review gate |

## Trust boundary

Every field is caller-supplied metadata. This validator does not verify signatures,
authenticate issuers, validate certificate paths or trust roots, fetch revocation
information, verify timestamp tokens, inspect payload bytes, or establish that claims
are true. A declared current revocation snapshot is not a live revocation check.
READY_FOR_INDEPENDENT_REVIEW is structural readiness only; it grants no authorization.
