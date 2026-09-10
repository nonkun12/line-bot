"""Compatibility wrapper that prevents false 'No safe target files selected' failures."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import line_development_worker as worker


def choose_files(client, instruction: str, files: list[str]) -> list[str]:
    """Use the AI selector first, then a deterministic safe fallback."""
    try:
        chosen = worker.choose_files_original(client, instruction, files)
    except Exception as exc:
        print(f"AI file selection failed; using safe fallback: {type(exc).__name__}: {exc}")
        chosen = []

    if chosen:
        return chosen[:worker.MAX_FILES]

    text = instruction.lower()
    tokens = [t for t in re.split(r"[^a-z0-9_ぁ-んァ-ヶ一-龯]+", text) if len(t) >= 2]

    priority = [
        ("app.py", ("line", "line bot", "bot", "webhook", "dashboard", "n8n", "push", "reply", "秘書", "開発")),
        ("bot_tools.py", ("memo", "note", "memory", "reminder", "メモ", "記憶", "リマインダー", "予定")),
        ("ai_client.py", ("ai", "groq", "model", "llm", "生成", "回答")),
        ("n8n_delegate.py", ("n8n", "delegate", "delegation", "委譲")),
        ("db.py", ("database", "db", "sqlite", "保存", "データベース")),
        ("README.md", ("readme", "documentation", "docs", "説明", "ドキュメント")),
    ]

    ranked: list[tuple[int, str]] = []
    for path in files:
        score = 0
        name = path.lower()
        for filename, keywords in priority:
            if path == filename:
                score += 5
                score += sum(2 for keyword in keywords if keyword in text)
        score += sum(1 for token in tokens if token in name)
        if score:
            ranked.append((score, path))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    fallback = [path for _, path in ranked[:worker.MAX_FILES]]

    # For ordinary LINE development requests, app.py is the safest useful target.
    if not fallback and "app.py" in files:
        fallback = ["app.py"]

    if fallback:
        print("Safe fallback targets selected:", ", ".join(fallback))
    return fallback


worker.choose_files_original = worker.choose_files
worker.choose_files = choose_files

if __name__ == "__main__":
    raise SystemExit(worker.main())
