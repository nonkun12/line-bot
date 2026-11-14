import pytest

from scripts import empty_repo_app_builder as builder


def test_independent_builder_rejects_missing_explicit_prefix_before_repo_creation(monkeypatch):
    monkeypatch.setenv("APP_REQUIREMENT", "create a new app")
    monkeypatch.setenv("APP_GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(
        builder,
        "create_repository",
        lambda *args, **kwargs: pytest.fail("repository must not be created"),
    )
    assert builder.main() == 80


def test_independent_builder_blocks_on_rea_failure_before_repo_creation(monkeypatch):
    monkeypatch.setenv("APP_REQUIREMENT", "アプリ開発: create a new app")
    monkeypatch.setenv("APP_GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(
        builder,
        "require_rea_pass",
        lambda root: (_ for _ in ()).throw(RuntimeError("blocked")),
    )
    monkeypatch.setattr(
        builder,
        "create_repository",
        lambda *args, **kwargs: pytest.fail("repository must not be created"),
    )
    assert builder.main() == 80
