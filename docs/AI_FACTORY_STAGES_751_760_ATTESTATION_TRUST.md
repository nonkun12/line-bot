# AI Factory Stages 751–760: Attestation and Trust Boundaries

Introduces a cryptographic verification primitive for signed evidence envelopes,
using HMAC-SHA256 and explicitly supplied trust-policy key material.

- 751: trust-policy key registry, issuer binding, active/revoked state.
- 752: canonical envelope serialization.
- 753: HMAC-SHA256 signature generation/verification.
- 754: audience and least-privilege scope enforcement.
- 755: issue/expiry and maximum-lifetime checks.
- 756: nonce replay checks against a caller-supplied ledger.
- 757: key revocation and issuer/key binding checks.
- 758: multi-attestation batch validation.
- 759: required-scope coverage gate.
- 760: integrated trust-boundary decision.

## Security limits

HMAC confirms that the envelope was produced by someone or something holding
the shared secret. It does not identify a natural person, provide public-key
non-repudiation, or prove the trusted key was provisioned securely. Key bytes
are passed in memory by the caller; no secret manager or PKI is integrated.
The nonce ledger is returned but not persisted, so replay prevention across
process restarts requires a durable trusted store outside this module.

The verifier does not run experiments, fetch evidence, authorize model changes,
or deploy. A passing gate is only READY_FOR_AUTHORIZED_EXTERNAL_REVIEW.
