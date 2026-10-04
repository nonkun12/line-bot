from pathlib import Path

from core.obsidian import ObsidianVault
from scripts.obsidian_mac_bridge import execute_local_job


def test_execute_local_job_uses_the_guarded_agent(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)

    result = execute_local_job(
        {
            "id": 1,
            "user_id": "U1",
            "message": "Obsidianに保存 notes/todo.md: bridge works",
            "claim_token": "token",
        },
        str(vault),
    )

    assert result["success"] is True
    assert "保存しました" in result["reply"]
    assert (vault / "notes/todo.md").read_text(encoding="utf-8") == "bridge works"


def test_execute_local_job_fails_closed_for_invalid_message(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()

    import pytest
    with pytest.raises(ValueError, match="message is required"):
        execute_local_job(
            {
                "id": 1,
                "user_id": "U1",
                "message": "",
                "claim_token": "token",
            },
            str(vault),
        )


def test_execute_local_job_uses_same_safe_path_contract(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    target = vault / "notes" / "todo.md"
    target.parent.mkdir()
    target.write_text("existing", encoding="utf-8")
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)

    result = execute_local_job(
        {
            "id": 2,
            "user_id": "U1",
            "message": "Obsidianに保存 notes/todo.md: overwrite",
            "claim_token": "token",
        },
        str(vault),
    )

    assert result["success"] is False
    assert "上書き" in result["reply"]
    assert target.read_text(encoding="utf-8") == "existing"
    assert ObsidianVault(vault).read_note("notes/todo.md") == "existing"
