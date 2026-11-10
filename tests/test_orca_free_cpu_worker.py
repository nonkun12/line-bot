from scripts.orca_free_cpu_worker import (
    safe_repo_path,
    unwrap_task_list,
    validate_patch,
)


def test_safe_repo_path_allows_only_new_app_and_proposal_scopes():
    assert safe_repo_path("apps/demo/app.py")
    assert safe_repo_path("docs/proposals/demo.md")
    assert not safe_repo_path("core/example.py")
    assert not safe_repo_path("tests/test_example.py")


def test_safe_repo_path_rejects_sensitive_and_traversal_paths():
    for path in (
        "../secrets/token.txt",
        ".github/workflows/unsafe.yml",
        "config.py",
        "requirements.txt",
        "apps/demo/.env",
        "apps/demo/../secrets/key.txt",
        "apps/demo\\..\\secrets\\key.txt",
    ):
        assert not safe_repo_path(path)


def test_unwrap_task_list_accepts_supported_container_shapes():
    task = {"task_id": "line-123", "request_text": "hello", "status": "queued"}
    assert unwrap_task_list({"tasks": [task]}) == [task]
    assert unwrap_task_list([task]) == [task]
    assert unwrap_task_list({"items": [task]}) == [task]


def test_validate_patch_accepts_only_new_files_in_allowed_scope():
    patch = (
        "diff --git a/apps/demo/app.py b/apps/demo/app.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/apps/demo/app.py\n"
        "@@ -0,0 +1 @@\n"
        "+print('hello')\n"
    )
    assert validate_patch(patch) == ["apps/demo/app.py"]


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
