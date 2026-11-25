"""One-command local LoopLab diagnostic launcher; loopback Ollama only."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from ipaddress import ip_address
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener


def _local_model_available(base_url: str, model: str) -> bool:
    parsed = urlsplit(base_url)
    try:
        loopback = ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        loopback = False
    if (
        parsed.scheme != "http" or not loopback or parsed.username is not None
        or parsed.password is not None or parsed.query or parsed.fragment
    ):
        raise ValueError("endpoint_must_be_loopback_http")
    opener = build_opener(ProxyHandler({}))
    request = Request(base_url.rstrip("/") + "/api/tags", headers={"Accept": "application/json"})
    try:
        with opener.open(request, timeout=5) as response:
            raw = response.read(1_000_001)
    except Exception as exc:
        raise ValueError(f"local_ollama_unavailable:{type(exc).__name__}") from None
    if len(raw) > 1_000_000:
        raise ValueError("local_ollama_response_too_large")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("local_ollama_response_invalid") from None
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        raise ValueError("local_ollama_model_list_invalid")
    names = {item.get("name") for item in models if isinstance(item, dict)}
    if model not in names:
        raise ValueError("local_model_not_installed")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.environ.get("RSI_LOCAL_MODEL_NAME", "lfm3:1.7b-qad-q4_0"))
    parser.add_argument("--base-url", default=os.environ.get("RSI_LOCAL_MODEL_BASE_URL", "http://127.0.0.1:11434"))
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 120:
        parser.error("--timeout must be between 1 and 120")
    os.environ["RSI_LOCAL_MODEL_BASE_URL"] = args.base_url
    os.environ["RSI_LOCAL_MODEL_PROTOCOL"] = "ollama"
    os.environ["RSI_LOCAL_MODEL_NAME"] = args.model
    os.environ["RSI_LOCAL_MODEL_TIMEOUT"] = str(args.timeout)
    try:
        _local_model_available(args.base_url, args.model)
    except ValueError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(f"Local Ollama ready: {args.model}")
    smoke = subprocess.run(
        [sys.executable, "-m", "scripts.run_looplab_local_eval", "--limit", "3",
         "--output", "artifacts/looplab-local-smoke.json"],
        env=os.environ.copy(), check=False,
    )
    if smoke.returncode:
        print("BLOCKED: local model smoke test failed; full evaluation was not started.", file=sys.stderr)
        return smoke.returncode
    full = subprocess.run(
        [sys.executable, "-m", "scripts.run_looplab_local_eval",
         "--output", "artifacts/looplab-local-eval.json"],
        env=os.environ.copy(), check=False,
    )
    return full.returncode


if __name__ == "__main__":
    raise SystemExit(main())
