from pathlib import Path

from scripts.orca_free_cpu_worker import (
    safe_app_path,
    unwrap_task_list,
    validate_patch,
)


def test_safe_app_path_allows_only_new_app_files():
    assert safe_app_path("apps/demo/app.py")
    assert safe_app_path("apps/demo/tests/test_app.py")
    assert not safe_app_path("docs/proposals/demo.md")
    assert not safe_app_path("core/example.py")
    assert not safe_app_path("tests/test_example.py")
    assert not safe_app_path("apps/demo/my app.py")


def test_safe_app_path_rejects_sensitive_and_traversal_paths():
    for path in (
        "../secrets/token.txt",
        ".github/workflows/unsafe.yml",
        "config.py",
        "requirements.txt",
        "apps/demo/.env",
        "apps/demo/../secrets/key.txt",
        "apps/demo\\..\\secrets\\key.txt",
    ):
        assert not safe_app_path(path)


def test_unwrap_task_list_accepts_supported_container_shapes():
    task = {"task_id": "line-123", "request_text": "hello", "status": "queued"}
    assert unwrap_task_list({"tasks": [task]}) == [task]
    assert unwrap_task_list([task]) == [task]
    assert unwrap_task_list({"items": [task]}) == [task]


def test_validate_patch_accepts_only_new_files_with_required_tests():
    patch = (
        "diff --git a/apps/demo/app.py b/apps/demo/app.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/apps/demo/app.py\n"
        "@@ -0,0 +1 @@\n"
        "+print('hello')\n"
        "diff --git a/apps/demo/tests/test_app.py b/apps/demo/tests/test_app.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/apps/demo/tests/test_app.py\n"
        "@@ -0,0 +1 @@\n"
        "+def test_demo():\n"
        "+    assert True\n"
    )
    assert validate_patch(patch) == ["apps/demo/app.py", "apps/demo/tests/test_app.py"]


def test_validate_patch_rejects_existing_file_modification():
    patch = (
        "diff --git a/apps/demo/app.py b/apps/demo/app.py\n"
        "--- a/apps/demo/app.py\n"
        "+++ b/apps/demo/app.py\n"
        "@@ -1 +1 @@\n-old\n+new\n"
    )
    try:
        validate_patch(patch)
    except RuntimeError as exc:
        assert "existing files" in str(exc)
    else:
        raise AssertionError("existing file modification should be rejected")


def test_validate_patch_rejects_workflow_changes():
    patch = (
        "diff --git a/.github/workflows/unsafe.yml b/.github/workflows/unsafe.yml\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/.github/workflows/unsafe.yml\n"
    )
    try:
        validate_patch(patch)
    except RuntimeError as exc:
        assert "forbidden output path" in str(exc)
    else:
        raise AssertionError("workflow patch should be rejected")


def test_isolated_test_runner_mounts_only_read_only_app_copy(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import scripts.orca_free_cpu_worker as worker

    app = tmp_path / "apps" / "demo"
    tests_dir = app / "tests"
    tests_dir.mkdir(parents=True)
    (app / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tests_dir / "test_app.py").write_text("def test_value():\n    assert True\n", encoding="utf-8")
    observed = {}

    def fake_run(command, *, timeout=120, input_text=None):
        observed["command"] = command
        mount = next(item for item in command if ":/workspace:ro" in item)
        staged = Path(mount.split(":/workspace:ro")[0])
        observed["files"] = sorted(str(p.relative_to(staged)) for p in staged.rglob("*") if p.is_file())
        observed["content"] = (staged / "apps/demo/app.py").read_text(encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(worker, "run", fake_run)
    result = worker.run_isolated_tests(
        ["apps/demo/app.py", "apps/demo/tests/test_app.py"], "demo"
    )
    assert result.returncode == 0
    command = observed["command"]
    assert "--network" in command and command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert "--user" in command and command[command.index("--user") + 1] == "65534:65534"
    assert observed["files"] == ["apps/demo/app.py", "apps/demo/tests/test_app.py"]
    assert observed["content"] == "VALUE = 1\n"
