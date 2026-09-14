"""Safe, optional Obsidian vault filesystem bridge."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


class ObsidianError(ValueError):
    """Raised for invalid or unsafe Obsidian vault operations."""


@dataclass(frozen=True)
class ObsidianVault:
    root: Path

    @classmethod
    def from_env(cls) -> "ObsidianVault | None":
        value = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
        return cls(Path(value).expanduser()) if value else None

    def _safe_path(self, relative_path: str) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ObsidianError("path must stay inside the Obsidian vault")
        root = self.root.expanduser().resolve()
        target = (root / candidate).resolve()
        if target != root and root not in target.parents:
            raise ObsidianError("path must stay inside the Obsidian vault")
        if target.suffix.lower() != ".md":
            raise ObsidianError("Obsidian notes must use .md files")
        return target

    def write_note(self, relative_path: str, content: str, *, append: bool = False) -> Path:
        target = self._safe_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with target.open(mode, encoding="utf-8") as handle:
            handle.write(content)
        return target

    def read_note(self, relative_path: str) -> str:
        return self._safe_path(relative_path).read_text(encoding="utf-8")

    def exists(self, relative_path: str) -> bool:
        return self._safe_path(relative_path).is_file()
