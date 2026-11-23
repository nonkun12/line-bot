# AI Factory Stages 401–405: Policy and Change Governance

## Scope
- **401 — Policy registry:** unique policy IDs, explicit versions, and SHA-256 content-digest shape.
- **402 — Dependency graph:** unique nodes, resolved references, and cycle rejection.
- **403 — Policy/evidence binding:** exact required policy coverage and non-empty evidence references.
- **404 — Change control:** revoked, expired, malformed, and future-dated events block readiness.
- **405 — Aggregate gate:** combines policy registry, dependency, evidence-binding, and change-control checks.

## Safety and limitations
Policy content hashes are caller-provided consistency declarations, not trusted signatures. Policy versions and evidence references do not authenticate policy origin, approval, enforcement, or evidence truth. Dependency acyclicity proves only graph structure, not that the policy is correct or complete. Event timestamps and states are caller-supplied and do not prove a trusted revocation or approval channel.

The aggregate is proposal-only. `execution_authorized` and `promotion_authorized` are always false. No policy is applied, no permissions are changed, no HOLD is released, and no production action, merge, or deployment is performed. No RSI/ASI claim is made.
