from pathlib import Path

import pytest

from scripts import empty_repo_app_builder as builder


@pytest.fixture(autouse=True)
def _make_builder_module_importable(monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(repo_root / "scripts"))


def test_configure_git_identity_sets_explicit_non_secret_bot_identity(monkeypatch):
    calls = []

    class Result:
        returncode = 0
        stderr = ""

    def fake_run(command, cwd, *, timeout=900):
        calls.append((command, cwd, timeout))
        return Result()

    monkeypatch.setattr(builder, "run", fake_run)

    builder.configure_git_identity("/tmp/generated-app")

    assert calls == [
        (["git", "config", "user.name", "github-actions[bot]"], "/tmp/generated-app", 60),
        (
            [
                "git",
                "config",
                "user.email",
                "41898282+github-actions[bot]@users.noreply.github.com",
            ],
            "/tmp/generated-app",
            60,
        ),
    ]
