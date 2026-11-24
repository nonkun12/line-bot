# LoopLab Simulator Producer contract v1

## Status

This is the required interface for a future independent Simulator Producer. The
producer is **not implemented or enabled yet**. Until a real producer supplies
the signed artifact and trusted holdout inputs, the post-run gate must report
`BLOCKED`. Do not create production-looking artifacts from the synthetic
retrieval fixture.

The producer is separate from LoopLab. It may obtain Baseline and Challenger
predictions from an explicitly configured local inference host, but it must
not patch source, alter the task queue, clear HOLD/STOP, merge, or deploy.
LoopLab only validates and scores supplied predictions.

## Files

The Distributed Loop post-run gate reads:

- `/tmp/looplab-simulator-output.json`: signed envelope below.
- `/tmp/looplab-held-out-dataset.json`: locked holdout rows.
- `/tmp/looplab-dataset-registry.json`: separately signed registry.
- `/tmp/looplab-safety-snapshot.json`: separately signed, short-lived safety state.

Each signed envelope has this outer form:

```json
{
  "payload": { "...": "canonical payload" },
  "signature": "lowercase hex HMAC-SHA256"
}
```

The signature is HMAC-SHA256 over UTF-8 JSON serialized with
`ensure_ascii=false`, sorted keys, compact separators `(',', ':')`, and
`allow_nan=false`. The Simulator key is
`LOOPLAB_SIMULATOR_HMAC_KEY`. Keys are provisioned by an authorized operator;
the producer must never create or print keys.

## Simulator payload

Required fields:

| Field | Requirement |
|---|---|
| `schema_version` | integer `1` |
| `producer_id` | `distributed-loop-simulator-producer.v1` |
| `experiment_id` | non-empty stable ID, at most 100 characters |
| `created_at` | Unix seconds; no more than 30 seconds in the future and no older than 300 seconds |
| `source_run_id` | exact current GitHub Actions `GITHUB_RUN_ID` |
| `source_commit_sha` | exact current `GITHUB_SHA` (40- or 64-character lowercase SHA) |
| `dataset_id` | `<experiment_id>:held-out` |
| `dataset_sha256` | SHA-256 of canonical held-out dataset JSON |
| `baseline`, `challenger` | distinct candidate identities, artifact SHA-256, and predictions |

Each candidate object contains:

```json
{
  "candidate_id": "distinct-non-empty-id",
  "artifact_sha256": "64 lowercase hex characters",
  "predictions": [
    {"sample_id": "dataset-sample-id", "output": "model output"}
  ]
}
```

Both prediction arrays must contain exactly one prediction for every holdout
sample ID: no missing IDs, duplicates, or unknown IDs. Prediction order is not
significant. The candidate artifact digest identifies the immutable candidate
artifact; it is not a substitute for the signed producer envelope.

## Gate behavior

The gate validates the Simulator HMAC, current run and commit binding, artifact
freshness, dataset digest/identity, exact prediction coverage, registry lock,
and fresh signed safety snapshot before evaluation. Any missing or mismatched
field yields `BLOCKED`; it is never converted to PASS or FAIL and is never
ingested into RSI.

The CI synthetic fixture remains a diagnostic only. Its result must retain
`production_evidence=false` and `rsi_ingestion=PROHIBITED_SYNTHETIC_FIXTURE`.

## Required producer implementation before production activation

1. Implement a separately invoked producer that receives an explicit run ID,
   commit SHA, locked dataset, and candidate artifact references.
2. Generate Baseline and Challenger predictions without changing candidate
   artifacts or repository state.
3. Emit the payload above and sign it using an externally provisioned key.
4. Upload the artifact to the same workflow run; never reuse artifacts from a
   prior run.
5. Add independent tests for wrong-run, wrong-commit, stale artifact, dataset
   substitution, duplicate/missing predictions, invalid signature, and local
   inference unavailability.
6. Keep hosted inference and paid fallback disabled. If the local inference
   host is unavailable, produce no signed success artifact; the gate remains
   BLOCKED.

No production producer, holdout registry, trust keys, or safety authority is
created by this contract document.
