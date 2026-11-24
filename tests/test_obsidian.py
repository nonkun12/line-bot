from pathlib import Path

import pytest

from core.obsidian import ObsidianError, ObsidianVault


def test_write_and_read_note(tmp_path: Path):
    vault = ObsidianVault(tmp_path)
    vault.write_note("projects/test.md", "# hello\n")
    assert vault.exists("projects/test.md")
    assert vault.read_note("projects/test.md") == "# hello\n"


def test_append_note(tmp_path: Path):
    vault = ObsidianVault(tmp_path)
    vault.write_note("test.md", "one\n")
    vault.write_note("test.md", "two\n", append=True)
    assert vault.read_note("test.md") == "one\ntwo\n"


@pytest.mark.parametrize(
    "path",
    ["../outside.md", "/tmp/outside.md", "note.txt", "README.MD.bak"],
)
def test_rejects_unsafe_or_non_markdown_paths(tmp_path: Path, path: str):
    vault = ObsidianVault(tmp_path)
    with pytest.raises(ObsidianError):
        vault.write_note(path, "blocked")


def test_rejects_symlink_escape(tmp_path: Path):
    outside = tmp_path.parent / "outside-obsidian-target"
    outside.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(outside, target_is_directory=True)

    vault = ObsidianVault(tmp_path)
    with pytest.raises(ObsidianError):
        vault.write_note("linked/escape.md", "blocked")


def test_missing_vault_fails_closed(tmp_path: Path):
    vault = ObsidianVault(tmp_path / "missing")
    with pytest.raises(ObsidianError):
        vault.list_notes()

## Backlog coverage tests
def test_obsidian_vault_from_env_is_optional_and_uses_configured_path(monkeypatch, tmp_path):
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    assert ObsidianVault.from_env() is None

    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    vault = ObsidianVault.from_env()
    assert vault is not None
    assert vault.root == tmp_path

@pytest.mark.parametrize(
    ("keyword", "limit"),
    [
        ("", 20),
        ("   ", 20),
        ("x" * 201, 20),
        ("needle", 0),
        ("needle", 21),
        ("needle", True),
    ],
)
def test_search_notes_rejects_invalid_keyword_and_limit(
    tmp_path: Path, keyword: str, limit: int
) -> None:
    vault = ObsidianVault(tmp_path)

    with pytest.raises(ObsidianError):
        vault.search_notes(keyword, limit=limit)

def test_search_notes_uses_unicode_casefold_for_matching(tmp_path: Path) -> None:
    vault = ObsidianVault(tmp_path)
    vault.write_note("unicode.md", "The German word is Straße.")

    assert vault.search_notes("STRASSE") == ["unicode.md"]

def test_search_notes_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside-secret.md"
    marker = "obsidian-outside-vault-secret-marker"
    outside.write_text(marker, encoding="utf-8")

    vault = ObsidianVault(tmp_path)
    link = tmp_path / "linked-outside.md"
    link.symlink_to(outside)

    assert vault.search_notes(marker) == []
    assert "linked-outside.md" not in vault.search_notes(marker)

