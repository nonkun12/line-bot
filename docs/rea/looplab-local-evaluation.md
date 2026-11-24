# LoopLab portable retrieval evaluation

This diagnostic is portable: it can run on a GitHub Actions CPU runner or any developer machine. A Mac is not required. The bundled corpus is synthetic/offline, so these results are never production evidence and must never be ingested into RSI.

## GitHub Actions (no model or Mac required)

The Distributed Loop workflow runs the deterministic baseline diagnostic automatically and uploads `looplab-baseline-diagnostic.json`. It reports the benchmark metrics only. It does not run a challenger model, create trusted simulator artifacts, or produce a production PASS/FAIL.

## Run a baseline anywhere (no model required)

```bash
python -m scripts.run_looplab_local_eval --baseline-only
```

## Optional local challenger comparison

Any host with Ollama and the exact model installed can run the challenger locally; this is not Mac-specific. The endpoint must be loopback HTTP only. No API key, hosted inference, or cloud fallback is used.

```bash
export RSI_LOCAL_MODEL_BASE_URL=http://127.0.0.1:11434
export RSI_LOCAL_MODEL_PROTOCOL=ollama
export RSI_LOCAL_MODEL_NAME=lfm3:1.7b-qad-q4_0

# Three-query smoke test
python -m scripts.run_looplab_local_eval --limit 3

# Full 60-query comparison
python -m scripts.run_looplab_local_eval
```

The one-command optional Ollama launcher is:

```bash
python -m scripts.start_looplab_local
```

It checks the local model, runs a 3-query smoke test, then the 60-query comparison. It does not install/start Ollama or alter repository state.

## Evidence boundary

`BASELINE_ONLY` and `COMPLETED_DIAGNOSTIC` are diagnostic statuses, not trusted PASS/FAIL. The bundled 10-document / 60-query corpus is synthetic. Results explicitly set `production_evidence=false` and `rsi_ingestion=PROHIBITED_SYNTHETIC_FIXTURE`; never sign or ingest them into RSI or use them to clear HOLD/STOP. Production evaluation still requires an independently trusted Simulator Producer, signed locked holdout registry/dataset, fresh signed safety snapshot, and provisioned trust keys. Missing inputs remain BLOCKED.
