# Local Creator/Critic runner

This is an opt-in, local-only execution path for the provider-neutral
Creator/Critic runtime. It can use the existing Bonsai and LFM loopback
profiles; it does not expose either model to GitHub-hosted Actions.

## Configure providers

Set `CREATOR_CRITIC_CREATOR_PROVIDER=bonsai` and
`CREATOR_CRITIC_CRITIC_PROVIDER=lfm` (or use a shared
`CREATOR_CRITIC_PROVIDER`). Set each selected profile's explicit
`*_BASE_URL` and `*_MODEL` values. The profile loader rejects non-loopback
URLs. Do not expose a local model port publicly.

## Evidence input

Supply a JSON object with numeric `accuracy`, `stability`, `efficiency`,
and `safety` values in the inclusive range 0–1, plus non-empty provenance
fields `source`, `method`, `measured_at`, and `evidence_ref`.
Only these allowlisted fields are passed into the model loop. The runner labels
them `CALLER_PROVIDED_NOT_VERIFIED`; it does not independently validate test
results or infer that the metrics are true. The Critic pass/score thresholds are
computed deterministically from those supplied numbers, not verified by either
model. The report marks this as
`DETERMINISTIC_FROM_UNVERIFIED_CALLER_INPUT`; model feedback is separate advisory text.

## Run

```bash
CREATOR_CRITIC_CREATOR_PROVIDER=bonsai \
CREATOR_CRITIC_CRITIC_PROVIDER=lfm \
CREATOR_CRITIC_BONSAI_BASE_URL=http://127.0.0.1:8081/v1 \
CREATOR_CRITIC_BONSAI_MODEL='<exact-id-from-v1-models>' \
CREATOR_CRITIC_LFM_BASE_URL='<verified-loopback-url>/v1' \
CREATOR_CRITIC_LFM_MODEL='<exact-id-from-v1-models>' \
python -m scripts.run_local_creator_critic \
  --objective 'Review the latest measured regression evidence' \
  --evidence /path/to/evidence.json \
  --output artifacts/local-creator-critic/report.json \
  --max-iterations 1
```

The exact model IDs and LFM endpoint must be read from the running local
servers; this document intentionally does not guess them.

The report is advisory. `promotion_eligible`, `source_changes`,
`queue_changes`, `approval_changes`, and `merge_or_deploy` remain false.
Independent tests, security gates, and human review are still required.
