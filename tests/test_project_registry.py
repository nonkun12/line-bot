import pytest

from core.project_registry import DEFAULT_PROJECT, ProjectRecord, ProjectRegistry


def test_default_project_is_ai_secretary():
    registry = ProjectRegistry()
    record = registry.require("line-bot")
    assert record.repository == "nonkun12/line-bot"
    assert record.project_type == "ai-secretary"
    assert record.active_branch == "main"


def test_registry_resolves_repository_without_guessing():
    registry = ProjectRegistry([
        DEFAULT_PROJECT,
        ProjectRecord(
            name="sample-app",
            repository="nonkun12/sample-app",
            project_type="software",
            runtime_target="render",
        ),
    ])
    assert registry.resolve_repository("nonkun12/sample-app").name == "sample-app"
    assert registry.resolve_repository("nonkun12/unknown") is None


def test_registry_round_trips_json(tmp_path):
    path = tmp_path / "projects.json"
    path.write_text(
        '[{"name":"todo-app","repository":"nonkun12/todo-app",'
        '"project_type":"software","supported_agents":["implementer","tester"]}]',
        encoding="utf-8",
    )
    record = ProjectRegistry.from_path(path).require("todo-app")
    assert record.repository == "nonkun12/todo-app"
    assert record.supported_agents == ("implementer", "tester")


def test_explicit_missing_registry_path_fails_closed(tmp_path):
    with pytest.raises(FileNotFoundError, match="project registry not found"):
        ProjectRegistry.from_path(tmp_path / "missing.json")


def test_registry_rejects_duplicate_name_or_repository():
    with pytest.raises(ValueError, match="duplicate project name"):
        ProjectRegistry([
            ProjectRecord(name="sample", repository="nonkun12/sample"),
            ProjectRecord(name="sample", repository="nonkun12/sample-2"),
        ])

    with pytest.raises(ValueError, match="duplicate project repository"):
        ProjectRegistry([
            ProjectRecord(name="sample", repository="nonkun12/sample"),
            ProjectRecord(name="sample-2", repository="nonkun12/sample"),
        ])


def test_registry_rejects_incomplete_json_entry(tmp_path):
    path = tmp_path / "projects.json"
    path.write_text('[{"name":"broken"}]', encoding="utf-8")
    with pytest.raises(ValueError, match="require name and repository"):
        ProjectRegistry.from_path(path)


def test_project_record_to_dict_serializes_supported_agents_as_list():
    record = ProjectRecord(
        name="sample-app",
        repository="nonkun12/sample-app",
        project_type="software",
        supported_agents=("implementer", "tester"),
    )

    serialized = record.to_dict()

    assert serialized["name"] == "sample-app"
    assert serialized["repository"] == "nonkun12/sample-app"
    assert serialized["supported_agents"] == ["implementer", "tester"]
    assert isinstance(serialized["supported_agents"], list)

## Backlog coverage tests
def test_registry_from_environment_loads_configured_file_and_defaults_when_unset(monkeypatch, tmp_path):
    path = tmp_path / "projects.json"
    path.write_text(
        '[{"name":"from-env","repository":"owner/from-env","project_type":"software"}]',
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJECT_REGISTRY_PATH", str(path))
    assert ProjectRegistry.from_environment().require("from-env").repository == "owner/from-env"

    monkeypatch.delenv("PROJECT_REGISTRY_PATH")
    assert ProjectRegistry.from_environment().require("line-bot") == DEFAULT_PROJECT


def test_registry_get_returns_none_for_unknown_names_and_normalizes_whitespace():
    registry = ProjectRegistry([ProjectRecord(name="sample", repository="owner/sample")])

    assert registry.get(" sample ") == registry.require("sample")
    assert registry.get("missing") is None


def test_registry_require_repository_returns_exact_match_and_rejects_unknown():
    registry = ProjectRegistry([ProjectRecord(name="sample", repository="owner/sample")])

    assert registry.require_repository("owner/sample").name == "sample"
    with pytest.raises(KeyError, match="unknown repository"):
        registry.require_repository("owner/missing")
