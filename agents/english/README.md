# English Learning Agent

Initial scaffold for English learning requests. External providers and persistent progress tracking are intentionally deferred until the routing contract is proven.

## Core-image vocabulary data

- `core_image.py` is the canonical main dictionary (119 headwords at the registry snapshot).
- `vocabulary_registry.json` records current headwords, historical branch snapshots, the 50 previously reserved candidate headwords, and the 10 existing flashcard verbs. Its blocked set is the exact union of those groups.
- `core_image_candidates.json` contains 65 pending candidates after duplicate filtering. The queue is not a list of registered or independently verified words.
- The auto-batch builder fails closed if the registry is missing, malformed, stale relative to the canonical dictionary, or internally inconsistent. It never re-adds a blocked headword.
- The existing flashcard set `get / take / make / have / keep / hold / run / turn / bring / leave` remains reserved and is not deleted or rewritten.
- New lessons still require separate content-quality review (core image, sense boundaries, collocations, natural examples) before dictionary registration. No learner message text is stored by this registry.
