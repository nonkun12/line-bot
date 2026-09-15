"""Fail-closed parsing helpers for machine-actionable LLM output.

This module is provider-neutral and side-effect free. It accepts only JSON
objects and supports common Markdown-fenced responses without guessing a
schema or executing model output. Callers decide the schema they require and
must validate it before applying any action.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class ParseAttempt:
    attempt: int
    source: str
    success: bool
    error: str = ""


@dataclass(frozen=True)
class ParseResult:
    value: dict[str, Any] | None
    attempts: tuple[ParseAttempt, ...]

    @property
    def ok(self) -> bool:
        return self.value is not None


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse one JSON object; never return arbitrary JSON or empty output."""
    clean = str(text or "").strip()
    if not clean:
        raise ValueError("empty model output")

    candidates: list[tuple[str, str]] = [("raw", clean)]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean, re.IGNORECASE | re.DOTALL)
    if fenced:
        candidates.append(("fenced", fenced.group(1)))

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", clean):
        try:
            candidate, _ = decoder.raw_decode(clean[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            candidates.append(("embedded_object", json.dumps(candidate, ensure_ascii=False)))
            break

    errors: list[str] = []
    seen: set[str] = set()
    for source, candidate_text in candidates:
        if candidate_text in seen:
            continue
        seen.add(candidate_text)
        try:
            value = json.loads(candidate_text)
        except json.JSONDecodeError as exc:
            errors.append(f"{source}: {exc}")
            continue
        if not isinstance(value, dict):
            errors.append(f"{source}: output must be a JSON object")
            continue
        return value
    raise ValueError("unable to parse JSON object: " + " | ".join(errors))


def parse_with_retries(
    outputs: list[str],
    validator: Callable[[dict[str, Any]], None] | None = None,
    max_attempts: int = 2,
) -> ParseResult:
    """Parse/validate a bounded list of model outputs and fail closed."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    attempts: list[ParseAttempt] = []
    for index, output in enumerate(outputs[:max_attempts], start=1):
        try:
            value = parse_json_object(output)
            if validator is not None:
                validator(value)
            attempts.append(ParseAttempt(index, "model", True))
            return ParseResult(value, tuple(attempts))
        except (ValueError, TypeError, KeyError) as exc:
            attempts.append(ParseAttempt(index, "model", False, str(exc)))

    return ParseResult(None, tuple(attempts))


def require_fields(value: Mapping[str, Any], required: set[str]) -> None:
    """Validate required top-level keys without coercing their values."""
    missing = sorted(field for field in required if field not in value)
    if missing:
        raise ValueError("missing required fields: " + ", ".join(missing))


__all__ = ["ParseAttempt", "ParseResult", "parse_json_object", "parse_with_retries", "require_fields"]
