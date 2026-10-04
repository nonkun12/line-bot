"""Safe, optional Obsidian vault filesystem bridge."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


class ObsidianError(ValueError):
    """Raised for invalid or unsafe Obsidian vault operations."""


@dataclass(frozen=True)
class ObsidianVault:
    """Bounded filesystem access limited to Markdown files in one vault."""

    root: Path

    @classmethod
    def from_env(cls) -> "ObsidianVault | None":
        value = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
        return cls(Path(value).expanduser()) if value else None

    def _root(self) -> Path:
        root = self.root.expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise ObsidianError("configured Obsidian vault does not exist or is not a directory")
        return root

    def _safe_path(self, relative_path: str) -> Path:
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ObsidianError("note path is required")
        candidate = Path(relative_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ObsidianError("path must stay inside the Obsidian vault")

        root = self._root()
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

    def list_notes(self, *, limit: int = 200) -> list[str]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ObsidianError("note list limit must be between 1 and 200")
        root = self._root()
        notes: list[str] = []
        for path in sorted(root.rglob("*.md")):
            resolved = path.resolve()
            if resolved != root and root not in resolved.parents:
                continue
            notes.append(resolved.relative_to(root).as_posix())
            if len(notes) >= limit:
                break
        return notes

    def search_notes(self, keyword: str, *, limit: int = 20) -> list[str]:
        if not isinstance(keyword, str) or not keyword.strip():
            raise ObsidianError("search keyword is required")
        if len(keyword) > 200:
            raise ObsidianError("search keyword is too long")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise ObsidianError("search limit must be between 1 and 20")

        needle = keyword.casefold()
        root = self._root()
        matches: list[str] = []
        for path in sorted(root.rglob("*.md")):
            resolved = path.resolve()
            if resolved != root and root not in resolved.parents:
                continue
            try:
                if needle in path.read_text(encoding="utf-8", errors="strict").casefold():
                    matches.append(resolved.relative_to(root).as_posix())
            except (OSError, UnicodeError):
                continue
            if len(matches) >= limit:
                break
        return matches
