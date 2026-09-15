from scripts.universal_app_builder import normalize_repo_name, parse_json, safe_relative_path, slugify, validate_files


def test_parse_json_scans_embedded_objects_without_looping():
    result = parse_json('note {not valid} then {"files": [], "summary": "ok"}')
    assert result["summary"] == "ok"


def test_slugify_prefers_stable_todo_repository_name():
    assert slugify("TODO管理Webアプリを作って") == "ai-todo-app"


def test_normalize_repo_name_rejects_unsafe_characters():
    assert normalize_repo_name(" ai todo / app ") == "ai-todo-app"


def test_relative_paths_never_allow_traversal_or_hidden_control_files():
    assert safe_relative_path("app.py") is True
    assert safe_relative_path("../app.py") is False
    assert safe_relative_path(".github/workflows/x.yml") is False
    assert safe_relative_path(".env") is False


def test_validate_files_requires_safe_supported_new_files_only():
    valid, _, files = validate_files([
        {"path": "app.py", "content": "print('ok')"},
        {"path": "tests.py", "content": "assert True"},
    ])
    assert valid is True
    assert len(files) == 2

    invalid, reason, _ = validate_files([
        {"path": "app.py", "content": "print('ok')"},
        {"path": "README.exe", "content": "no"},
    ])
    assert invalid is False
    assert "unsafe path" in reason
