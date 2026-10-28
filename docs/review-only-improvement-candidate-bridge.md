# Review-only improvement candidate bridge

This module is a bounded, review-only storage/presentation primitive for
structured proposals from self-improvement and Idea AI. It is intentionally
**not wired into the autonomous execution queue in this change**.

## Contract

- Accept only structured rows with source `self_improvement` or `idea_ai`.
- Normalize a deterministic key and deduplicate repeated candidates.
- Keep at most 50 candidates; strip control characters and bound text fields.
- Persist only allowlisted fields; unknown fields (including instructions,
  authorization flags, and secrets) are discarded.
- Every stored candidate has `execution_authorized: false`.
- Produce a Markdown summary for human review only.
- Invalid input or a corrupt existing store fails closed without overwriting it.

## CLI

```sh
python scripts/review_candidate_bridge.py \
  --input /tmp/review-candidates.json \
  --store /tmp/review-candidates.jsonl \
  --summary /tmp/review-candidates-summary.md
```

Input is a JSON list of objects with `source`, `title`, and optional
`source_id`, `rationale`, and `status`. This change adds no producer, queue
consumer, issue/PR creation, workflow wiring, or approval bypass. A follow-up
must wire actual proposal producers to this bridge and publish the summary as
an artifact/Step Summary, while retaining human review, catalog registration,
and the existing approval label before any execution task can be queued.
