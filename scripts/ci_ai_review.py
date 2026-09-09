#!/usr/bin/env python3
"""Run an AI blocking review for a pull-request diff in GitHub Actions."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = os.environ.get("AI_REVIEW_MODEL", "openai/gpt-oss-20b")
MAX_DIFF_CHARS = int(os.environ.get("AI_REVIEW_MAX_DIFF_CHARS", "120000"))


def git_diff() -> str:
    result = subprocess.run(
        ["git", "diff", "origin/main...HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git diff failed")
    return result.stdout


def call_groq(diff: str) -> dict:
    token = os.environ.get("GROQ_API_KEY", "").strip()
    if not token:
        raise RuntimeError("GROQ_API_KEY is not configured for AI Code Review")

    prompt = f"""You are the blocking code reviewer for the nonkun12/line-bot repository.
Review ONLY the supplied pull-request diff. Focus on correctness, security, regressions,
state/approval safety, concurrency/lease safety, GitHub/CI behavior, and preservation of
existing LINE Notes/Memory/Reminder behavior.

Return JSON only with this exact shape:
{{
  \"verdict\": \"PASS\" | \"FAIL\",
  \"summary\": \"one concise paragraph\",
  \"findings\": [
    {{\"severity\": \"blocking\" | \"warning\", \"file\": \"path\", \"detail\": \"actionable finding\"}}
  ]
}}

Use FAIL only for issues that should block merge. Do not invent findings unrelated to the diff.

PULL REQUEST DIFF:
{diff[:MAX_DIFF_CHARS]}
"""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a strict senior software engineer. Output JSON only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": 1400,
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Groq review request failed: HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Groq review request failed: {exc}") from exc

    data = json.loads(body)
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        raise RuntimeError("Groq review returned no content")
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:]
    review = json.loads(content.strip())
    if review.get("verdict") not in {"PASS", "FAIL"}:
        raise RuntimeError("AI review returned an invalid verdict")
    return review


def main() -> int:
    try:
        diff = git_diff()
        if not diff.strip():
            print("No pull-request diff found; failing closed.")
            return 1
        review = call_groq(diff)
    except Exception as exc:
        print(f"AI Code Review error: {exc}")
        return 1

    summary = review.get("summary", "")
    verdict = review["verdict"]
    print(f"AI Code Review verdict: {verdict}")
    print(summary)
    for finding in review.get("findings", []):
        print(
            f"- [{finding.get('severity', 'warning')}] "
            f"{finding.get('file', '?')}: {finding.get('detail', '')}"
        )

    github_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if github_summary:
        with open(github_summary, "a", encoding="utf-8") as handle:
            handle.write(f"## AI Code Review: **{verdict}**\n\n")
            handle.write(summary + "\n\n")
            for finding in review.get("findings", []):
                handle.write(
                    f"- **{finding.get('severity', 'warning')}** — "
                    f"`{finding.get('file', '?')}`: {finding.get('detail', '')}\n"
                )

    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
