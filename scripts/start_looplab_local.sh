#!/usr/bin/env bash
# One-command local LoopLab diagnostic: verify the loopback Ollama model,
# run a bounded smoke test, then execute the full offline comparison.
set -euo pipefail

export RSI_LOCAL_MODEL_BASE_URL="${RSI_LOCAL_MODEL_BASE_URL:-http://127.0.0.1:11434}"
export RSI_LOCAL_MODEL_PROTOCOL="${RSI_LOCAL_MODEL_PROTOCOL:-ollama}"
export RSI_LOCAL_MODEL_NAME="${RSI_LOCAL_MODEL_NAME:-lfm3:1.7b-qad-q4_0}"
export RSI_LOCAL_MODEL_TIMEOUT="${RSI_LOCAL_MODEL_TIMEOUT:-60}"

python - <<'PY'
import json
import os
from urllib.request import ProxyHandler, build_opener, Request
from urllib.error import URLError

base = os.environ["RSI_LOCAL_MODEL_BASE_URL"].rstrip("/")
if base != "http://127.0.0.1:11434":
    # A different loopback port is allowed; remote hosts and non-HTTP schemes are not.
    from urllib.parse import urlsplit
    from ipaddress import ip_address
    parsed = urlsplit(base)
    try:
        loopback = ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        loopback = False
    if parsed.scheme != "http" or not loopback or parsed.username or parsed.password:
        raise SystemExit("BLOCKED: endpoint must be an unauthenticated loopback HTTP URL")

try:
    opener = build_opener(ProxyHandler({}))
    req = Request(base + "/api/tags", headers={"Accept": "application/json"})
    with opener.open(req, timeout=5) as response:
        payload = json.loads(response.read(1_000_001).decode("utf-8"))
    names = {item.get("name") for item in payload.get("models", []) if isinstance(item, dict)}
except Exception as exc:
    raise SystemExit(f"BLOCKED: local Ollama is unavailable ({type(exc).__name__}); start it locally and retry")

model = os.environ["RSI_LOCAL_MODEL_NAME"]
if model not in names:
    available = ", ".join(sorted(str(name) for name in names)) or "(none)"
    raise SystemExit(f"BLOCKED: model {model!r} is not installed locally. Available: {available}")
print(f"Local endpoint OK; model available: {model}")
PY

python -m scripts.run_looplab_local_eval --limit 3 --output artifacts/looplab-local-smoke.json
python -m scripts.run_looplab_local_eval --output artifacts/looplab-local-eval.json
