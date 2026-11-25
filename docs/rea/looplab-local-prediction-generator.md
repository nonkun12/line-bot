# LoopLab local prediction generator

`scripts/generate_looplab_local_predictions.py` runs two explicitly named local
models against the same caller-supplied holdout dataset. The endpoint is validated
by `core.local_model_client`: HTTP loopback only, proxies disabled, redirects
blocked, no credentials, no retries, no hosted API or cloud fallback.

Dataset format:

```json
[
  {"sample_id": "case-001", "prompt": "Input for the model", "system_prompt": "Optional per-case system instruction"}
]
```

Run locally after the holdout owner has authorized access and both exact model
tags are installed in Ollama:

```sh
python -m scripts.generate_looplab_local_predictions \
  --dataset /path/to/locked-held-out-dataset.json \
  --baseline-model <installed-baseline-tag> \
  --challenger-model <installed-challenger-tag>
```

Outputs default to `/tmp/looplab-baseline-predictions.json` and
`/tmp/looplab-challenger-predictions.json`. Both candidates must complete
successfully before files are emitted. The command does not install or pull
models, start Ollama, create candidate artifacts, sign Simulator evidence,
create a registry or safety snapshot, or ingest RSI evidence.

The output arrays can be supplied to
`scripts.produce_looplab_simulator_artifact` together with immutable candidate
artifact files. That separate producer still requires a current run/commit
binding and externally provisioned signing key. A trusted dataset registry and
fresh signed safety snapshot remain independently required. This generator's
output alone is diagnostic material, never production evidence.
