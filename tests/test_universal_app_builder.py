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
        {"path": "run.py", "content": "print('run')"},
        {"path": "README.md", "content": "# app"},
        {"path": "requirements.txt", "content": "pytest"},
        {"path": "tests/test_app.py", "content": "def test_ok(): pass"},
    ])
    assert valid is True
    assert len(files) == 5

    invalid, reason, _ = validate_files([
        {"path": "app.py", "content": "print('ok')"},
        {"path": "README.exe", "content": "no"},
    ])
    assert invalid is False
    assert "unsafe path" in reason


def test_validate_files_requires_complete_runnable_project_manifest():
    valid, _, _ = validate_files([
        {"path": "app.py", "content": "print('ok')"},
        {"path": "run.py", "content": "print('run')"},
        {"path": "README.md", "content": "# app"},
        {"path": "requirements.txt", "content": "pytest"},
        {"path": "tests/test_app.py", "content": "def test_ok(): pass"},
    ])
    assert valid is True


def test_validate_files_rejects_partial_app_without_manifest_or_tests():
    valid, reason, _ = validate_files([
        {"path": "app.py", "content": "print('ok')"},
        {"path": "README.md", "content": "# app"},
    ])
    assert valid is False
    assert "required project files missing" in reason or "pytest file" in reason


def test_validate_files_requires_single_user_entrypoint():
    valid, reason, _ = validate_files([
        {"path": "app.py", "content": "print('ok')"},
        {"path": "README.md", "content": "# app"},
        {"path": "requirements.txt", "content": "pytest"},
        {"path": "tests/test_app.py", "content": "def test_ok(): pass"},
    ])
    assert valid is False
    assert "run.py entrypoint" in reason


def test_clone_uses_clean_url_and_does_not_persist_raw_token(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, cwd, *, timeout=900, env=None):
        captured["cmd"] = cmd
        captured["env"] = env
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(app_builder, "run", fake_run)
    app_builder.clone_repo("nonkun12/example-app", "unit-test-token", tmp_path / "repo", tmp_path)

    assert "https://github.com/nonkun12/example-app.git" in captured["cmd"]
    assert all("unit-test-token" not in item for item in captured["cmd"])
    assert "unit-test-token" not in captured["env"]["GIT_CONFIG_VALUE_1"]
    assert captured["env"]["GIT_CONFIG_VALUE_0"] == ""
    assert "AUTHORIZATION: basic " in captured["env"]["GIT_CONFIG_VALUE_1"]


def test_generated_tests_receive_no_environment_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_GITHUB_TOKEN", "app-token-for-test")
    monkeypatch.setenv("GROQ_API_KEY", "model-key-for-test")
    monkeypatch.setenv("INTERNAL_PUSH_KEY", "internal-key-for-test")
    captured_envs = []

    def fake_run(cmd, cwd, *, timeout=900, env=None):
        captured_envs.append(dict(env or {}))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(app_builder, "run", fake_run)
    passed, _ = app_builder.run_tests(tmp_path)

    assert passed is True
    assert len(captured_envs) == 2
    for env in captured_envs:
        assert "APP_GITHUB_TOKEN" not in env
        assert "GROQ_API_KEY" not in env
        assert "INTERNAL_PUSH_KEY" not in env
        assert not any("TOKEN" in key.upper() or "SECRET" in key.upper() or "API_KEY" in key.upper() for key in env)


def test_authenticated_push_pins_remote_and_disables_generated_hooks(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, cwd, *, timeout=900, env=None):
        captured["cmd"] = cmd
        captured["env"] = env
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(app_builder, "run", fake_run)
    app_builder.push_branch(tmp_path, "nonkun12/example-app", ["--set-upstream", "origin", "ai-dev/test"], "push-token")

    assert "remote.origin.url=https://github.com/nonkun12/example-app.git" in captured["cmd"]
    assert "push-token" not in " ".join(captured["cmd"])
    assert captured["env"]["GIT_CONFIG_KEY_2"] == "core.hooksPath"
    assert "push-token" not in captured["env"]["GIT_CONFIG_VALUE_1"]
    assert any(item.startswith("core.hooksPath=") for item in captured["cmd"])


def test_app_builder_removes_credentials_from_parent_environment():
    root = Path(__file__).resolve().parents[1]
    standalone = (root / "scripts" / "universal_app_builder.py").read_text(encoding="utf-8")
    empty_repo = (root / "scripts" / "empty_repo_app_builder.py").read_text(encoding="utf-8")

    for source in (standalone, empty_repo):
        assert 'os.environ.pop("APP_GITHUB_TOKEN", "")' in source
        assert 'os.environ.pop("GROQ_API_KEY", "")' in source
