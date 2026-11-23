# AI Factory Stages 406–410: Auditability and Evidence Lineage

## Scope
- **406 — Evidence lineage:** require source, producer, creation time, and SHA-256 digest declarations for every evidence record.
- **407 — Audit sequence integrity:** require unique event IDs, zero-based contiguous sequence numbers, and explicit previous-event links.
- **408 — Replay/duplicate detection:** reject repeated evidence IDs and repeated caller-declared fingerprints.
- **409 — Evaluator separation:** require a distinct declared evaluator and explicit separation attestation for each required scope.
- **410 — Aggregate auditability gate:** combine the four checks and fail closed if any check fails.

## Safety and limitations
All inputs are caller-supplied declarations. A hash is a consistency checksum, not a signature or proof of source authenticity. A linked event sequence does not prove tamper resistance, completeness, trusted timestamps, or custody. Duplicate fingerprints detect only duplicates represented by the supplied values. Distinct evaluator identifiers and attestations do not prove organizational independence, competence, blindness, or freedom from conflicts.

The aggregate is proposal-only. `execution_authorized` and `promotion_authorized` are always false. No experiments, training, model/weight changes, HOLD release, permission changes, production actions, merge, or deployment are performed. No RSI/ASI claim is made.
