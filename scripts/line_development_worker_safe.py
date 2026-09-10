"""Compatibility wrapper for reliable, bounded LINE development automation."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import line_development_worker as worker

PATCH_CONTEXT_CHARS = 7000
PATCH_MAX_TOKENS = 2200


def choose_files(client, instruction: str, files: list[str]) -> list[str]:
    """Select a very small safe scope; fall back deterministically."""
    try:
        chosen = worker.choose_files_original(client, instruction, files)
    except Exception as exc:
        print(f"AI file selection failed; using safe fallback: {type(exc).__name__}: {exc}")
        chosen = []
    if chosen:
        return chosen[:1]

    text = instruction.lower()
    priority = [
        ("app.py", ("line", "line bot", "bot", "webhook", "dashboard", "n8n", "push", "reply", "秘書", "開発")),
        ("bot_tools.py", ("memo", "note", "memory", "reminder", "メモ", "記憶", "リマインダー", "予定")),
        ("ai_client.py", ("ai", "groq", "model", "llm", "生成", "回答")),
        ("n8n_delegate.py", ("n8n", "delegate", "delegation", "委譲")),
        ("db.py", ("database", "db", "sqlite", "保存", "データベース")),
        ("README.md", ("readme", "documentation", "docs", "説明", "ドキュメント")),
    ]
    for path, keywords in priority:
        if path in files and any(keyword in text for keyword in keywords):
            print("Safe fallback target selected:", path)
            return [path]
    if "app.py" in files:
        print("Safe fallback target selected: app.py")
        return ["app.py"]
    return files[:1]


def load_context(paths: list[str]) -> str:
    chunks: list[str] = []
    for path in paths[:1]:
        text = (ROOT / path).read_text(encoding="utf-8")
        chunks.append(f"===== {path} =====\n{text[:PATCH_CONTEXT_CHARS]}")
    return "\n\n".join(chunks)


def ask_for_patch(client, system: str, prompt: str) -> str:
    response = client.chat.completions.create(
        model=worker.MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        max_tokens=PATCH_MAX_TOKENS,
    )
    return response.choices[0].message.content or ""


def main() -> int:
    instruction = os.environ.get("DEV_INSTRUCTION", "").strip()
    user_id = os.environ.get("DEV_USER_ID", "")
    if not instruction:
        print("No development instruction supplied.")
        return 2

    client = worker.Groq(api_key=os.environ["GROQ_API_KEY"])
    files = worker.repo_files()
    chosen = choose_files(client, instruction, files)
    if not chosen:
        print("No safe target files selected.")
        return 1

    context = load_context(chosen)
    system = (
        "You are a senior software engineer. Implement exactly one small requested change. "
        "Return ONLY a valid unified git diff with no markdown fences and no explanation. "
        "Modify ONLY the supplied target file. Keep the patch minimal."
    )
    prompt = (
        f"Instruction from LINE:\n{instruction}\n\n"
        f"Target file and current contents:\n{context}\n\n"
        "Return a non-empty unified diff when the instruction requests a change. "
        "The diff must use the exact target path."
    )

    raw = ask_for_patch(client, system, prompt)
    patch = worker.extract_diff(raw)
    ok, detail = worker.validate_diff(patch)
    if not ok:
        print(f"Rejected patch: {detail}")
        if raw.strip():
            print("Model response preview:")
            print(raw[:2000])
        return 1

    passed, test_output = worker.apply_and_test(patch)
    attempts = 1
    if not passed:
        repair_prompt = (
            f"Instruction:\n{instruction}\n\nPrevious patch:\n{patch}\n\n"
            f"Pytest failure:\n{test_output[-5000:]}\n\n"
            f"Current file:\n{load_context(chosen)}\n\n"
            "Return ONLY a corrected unified diff for the same file."
        )
        repaired = worker.extract_diff(ask_for_patch(client, system, repair_prompt))
        ok2, detail2 = worker.validate_diff(repaired)
        if not ok2:
            worker.run(["git", "checkout", "--", *chosen])
            print(f"Repair rejected: {detail2}")
            return 1
        worker.run(["git", "checkout", "--", *chosen])
        passed, test_output = worker.apply_and_test(repaired)
        patch = repaired
        attempts = 2

    if not passed:
        worker.run(["git", "checkout", "--", *chosen])
        print(f"Development failed after {attempts} attempt(s).\n{test_output[-8000:]}")
        return 1

    status = worker.run(["git", "status", "--short"])
    if not status.stdout.strip():
        print("Tests passed but no files changed.")
        return 0

    branch = f"line-dev/{os.environ.get('GITHUB_RUN_ID', 'manual')}"
    branch_check = worker.run(["git", "checkout", "-b", branch])
    if branch_check.returncode != 0:
        print(branch_check.stderr[-2000:])
        return 1
    worker.run(["git", "config", "user.name", "line-development-worker"])
    worker.run(["git", "config", "user.email", "line-development-worker@users.noreply.github.com"])
    worker.run(["git", "add", "--", *chosen])
    commit = worker.run(["git", "commit", "-m", "feat: implement LINE development request"])
    if commit.returncode != 0:
        print(commit.stderr[-2000:])
        return 1
    push = worker.run(["git", "push", "--set-upstream", "origin", branch])
    if push.returncode != 0:
        print(push.stderr[-2000:])
        return 1

    pr_body = (
        "## LINE development request\n\n"
        f"{instruction}\n\n"
        f"User: `{user_id}`\n\n"
        f"Pytest: PASS\nRepair attempts: {attempts}\n\n"
        "This PR was created by the guarded LINE development worker."
    )
    pr = worker.run([
        "gh", "pr", "create", "--base", "main", "--head", branch,
        "--title", "feat: LINE development request", "--body", pr_body,
    ])
    print(f"Development complete.\n{pr.stdout[-4000:]}\n{test_output[-4000:]}")
    return 0 if pr.returncode == 0 else 1


worker.choose_files_original = worker.choose_files
worker.choose_files = choose_files

if __name__ == "__main__":
    raise SystemExit(main())
