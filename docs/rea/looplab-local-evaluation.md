# LoopLab local retrieval evaluation

Runnable local diagnostic only; not production evidence.

## Configure local Ollama

```bash
export RSI_LOCAL_MODEL_BASE_URL=http://127.0.0.1:11434
export RSI_LOCAL_MODEL_PROTOCOL=ollama
export RSI_LOCAL_MODEL_NAME=lfm3:1.7b-qad-q4_0
```

Set the model name to the exact model installed locally. No API key is needed.

## Run

```bash
# Baseline only; no model required
python -m scripts.run_looplab_local_eval --baseline-only

# Three-query local inference smoke test
python -m scripts.run_looplab_local_eval --limit 3

# Full 60-query comparison
python -m scripts.run_looplab_local_eval
```

Output: `artifacts/looplab-local-eval.json`. The smoke test makes one local inference call per query; the full run makes 60. `BASELINE_ONLY` and `COMPLETED_DIAGNOSTIC` are diagnostic statuses, not trusted PASS/FAIL. The bundled 10-document / 60-query corpus is synthetic. Results explicitly set `production_evidence=false` and `rsi_ingestion=PROHIBITED_SYNTHETIC_FIXTURE`; never sign or ingest them into RSI or use them to clear HOLD/STOP. Invalid model output blocks the run. The local model client enforces loopback HTTP, disables proxies and redirects, and has no cloud fallback. This command does not modify repository state or trigger the Distributed Loop.
