from __future__ import annotations

import re
from dataclasses import dataclass

@dataclass(frozen=True)
class LoopRoute:
    manager_required: bool
    idea_required: bool
    reason: str

_PATH_RE = re.compile(r'(?:core|tests|scripts|app|src)/[A-Za-z0-9_./-]+\.py|(?<![A-Za-z0-9_./-])[A-Za-z0-9_-]+\.py')

def explicit_target(instruction: str, available_files: set[str]) -> str | None:
    candidates = []
    for match in _PATH_RE.findall(instruction):
        normalized = match.strip("`'.,:;()[]{}")
        if normalized in available_files and normalized not in candidates:
            candidates.append(normalized)
    return candidates[0] if len(candidates) == 1 else None

def route_task(instruction: str, available_files: set[str]) -> LoopRoute:
    target = explicit_target(instruction, available_files)
    if target is not None and not is_protected(target):
        return LoopRoute(False, False, f"explicit safe target: {target}")
    return LoopRoute(True, False, "target requires manager selection")

def is_protected(path: str) -> bool:
    return path.startswith((".git/", ".github/workflows/")) or path in {"render.yaml", "Dockerfile"}
