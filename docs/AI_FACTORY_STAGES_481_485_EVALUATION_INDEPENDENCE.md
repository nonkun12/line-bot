# AI Factory Stages 481–485: Evaluation Independence

- **481 — Split disjointness:** detect duplicate and cross-split sample identifiers.
- **482 — Dataset lineage:** require dataset version identities and lineage references.
- **483 — Calibration evidence:** enforce declared sample minimums and calibration error limits.
- **484 — External reference:** require protocol- and metric-compatible reference declarations.
- **485 — Aggregate gate:** fail closed on any failed check or unresolved HOLD.

## Safety and limitations
All identifiers, references, scores, and calibration metadata are caller-supplied and unauthenticated. Disjoint identifiers do not prove semantic independence or absence of leakage; lineage strings do not prove provenance; declared external references are not fetched or validated. Calibration declarations do not establish statistical validity. READY_FOR_REVIEW is not certification. No evaluation, training, model change, HOLD release, execution, promotion, merge, or deployment occurs.
