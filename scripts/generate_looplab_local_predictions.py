"""Generate Baseline and Challenger predictions with loopback-only local models.

This stage only writes prediction JSON arrays. It never signs Simulator evidence,
creates trust inputs, executes repository candidates, or sends data to hosted APIs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from core.local_model_client import LocalModelClient, LocalModelError

_MAX_SAMPLES = 10_000
_MAX_PROMPT_CHARS = 100_000
_MAX_OUTPUT_CHARS = 100_000
_DEFAULT_SYSTEM = "Answer the supplied task accurately. Return only the answer."


def _read_dataset(path: Path) -> list[dict[str, str]]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("dataset_unavailable_or_invalid") from None
    if not isinstance(rows, list) or not rows or len(rows) > _MAX_SAMPLES:
        raise ValueError("dataset_size_invalid")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("dataset_row_invalid")
        sample_id, prompt = row.get("sample_id"), row.get("prompt")
        system_prompt = row.get("system_prompt", _DEFAULT_SYSTEM)
        if (not isinstance(sample_id, str) or not sample_id.strip()
                or len(sample_id) > 200 or sample_id in seen
                or not isinstance(prompt, str) or not prompt.strip()
                or len(prompt) > _MAX_PROMPT_CHARS
                or not isinstance(system_prompt, str) or not system_prompt.strip()
                or len(system_prompt) > _MAX_PROMPT_CHARS):
            raise ValueError("dataset_sample_schema_invalid")
        seen.add(sample_id)
        normalized.append({"sample_id": sample_id, "prompt": prompt, "system_prompt": system_prompt})
    return normalized


def _generate(client: LocalModelClient, model: str, rows: list[dict[str, str]], max_tokens: int) -> list[dict[str, str]]:
    predictions: list[dict[str, str]] = []
    for row in rows:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": row["system_prompt"]},
                {"role": "user", "content": row["prompt"]},
            ],
            temperature=0.0,
            max_completion_tokens=max_tokens,
            include_reasoning=False,
        )
        output = response.choices[0].message.content
        if not isinstance(output, str) or not output.strip() or len(output) > _MAX_OUTPUT_CHARS:
            raise ValueError("local_prediction_output_invalid")
        predictions.append({"sample_id": row["sample_id"], "output": output.strip()})
    return predictions


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".looplab-predictions-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _ensure_distinct_outputs(outputs: list[Path], inputs: list[Path]) -> None:
    resolved = [path.resolve() for path in outputs]
    if len(set(resolved)) != len(resolved) or any(item in resolved for item in (p.resolve() for p in inputs)):
        raise ValueError("output_paths_must_be_distinct_from_inputs")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, help="Locked holdout JSON: [{sample_id,prompt,system_prompt?}]")
    parser.add_argument("--baseline-model", required=True, help="Exact locally installed Ollama model tag")
    parser.add_argument("--challenger-model", required=True, help="Exact locally installed Ollama model tag")
    parser.add_argument("--base-url", default=os.environ.get("RSI_LOCAL_MODEL_BASE_URL", "http://127.0.0.1:11434"))
    parser.add_argument("--protocol", choices=("ollama", "openai-compatible"), default=os.environ.get("RSI_LOCAL_MODEL_PROTOCOL", "ollama"))
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--baseline-output", default="/tmp/looplab-baseline-predictions.json")
    parser.add_argument("--challenger-output", default="/tmp/looplab-challenger-predictions.json")
    args = parser.parse_args()

    if not args.baseline_model.strip() or not args.challenger_model.strip() or args.baseline_model == args.challenger_model:
        print("BLOCKED: candidate_models_must_be_distinct", file=sys.stderr)
        return 2
    if not 1 <= args.max_tokens <= 8192:
        print("BLOCKED: max_tokens_invalid", file=sys.stderr)
        return 2

    dataset_path = Path(args.dataset)
    baseline_path, challenger_path = Path(args.baseline_output), Path(args.challenger_output)
    try:
        _ensure_distinct_outputs([baseline_path, challenger_path], [dataset_path])
        rows = _read_dataset(dataset_path)
        baseline_client = LocalModelClient(args.base_url, args.baseline_model, args.protocol, args.timeout)
        challenger_client = LocalModelClient(args.base_url, args.challenger_model, args.protocol, args.timeout)
        baseline = _generate(baseline_client, args.baseline_model, rows, args.max_tokens)
        challenger = _generate(challenger_client, args.challenger_model, rows, args.max_tokens)
        # Write only after both candidates completed successfully; no partial success artifact.
        _write_json(baseline_path, baseline)
        try:
            _write_json(challenger_path, challenger)
        except Exception:
            baseline_path.unlink(missing_ok=True)
            raise
    except (OSError, ValueError, LocalModelError) as exc:
        print("BLOCKED: " + str(exc)[:200], file=sys.stderr)
        return 2

    print(json.dumps({
        "status": "PREDICTIONS_CREATED",
        "sample_count": len(rows),
        "baseline_model": args.baseline_model,
        "challenger_model": args.challenger_model,
        "baseline_output": str(baseline_path),
        "challenger_output": str(challenger_path),
        "inference": "loopback_local_only",
        "hosted_api": False,
        "cloud_fallback": False,
        "signature_created": False,
        "production_evidence": False,
        "rsi_ingestion": "PROHIBITED_UNTIL_SIGNED_PRODUCER_AND_TRUSTED_REGISTRY",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
