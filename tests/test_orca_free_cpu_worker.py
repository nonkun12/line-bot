from scripts.orca_free_cpu_worker import (
    safe_repo_path,
    unwrap_task_list,
    validate_patch,
)


def test_safe_repo_path_accepts_narrow_source_files():
    assert safe_repo_path("core/example.py")
    assert safe_repo_path("docs/worker.md")


def test_safe_repo_path_rejects_sensitive_and_traversal_paths():
    for path in (
        "../secrets/token.txt",
        ".github/workflows/unsafe.yml",
        "config.py",
        "requirements.txt",
        "apps/.env",
        "core\\..\\secrets\\key.txt",
    ):
        assert not safe_repo_path(path)


def test_unwrap_task_list_accepts_documented_container_shapes():
    task = {"task_id": "line-123", "request_text": "hello", "status": "queued"}
    assert unwrap_task_list({"tasks": [task]}) == [task]
    assert unwrap_task_list([task]) == [task]
    assert unwrap_task_list({"items": [task]}) == [task]


def test_validate_patch_accepts_only_bounded_allowed_paths():
    patch = (
        "diff --git a/core/example.py b/core/example.py\n"
        "--- a/core/example.py\n"
        "+++ b/core/example.py\n"
        "@@ -1 +1 @@\n"
        "-old\n+new\n"
    )
    assert validate_patch(patch) == ["core/example.py"]


def test_validate_patch_rejects_workflow_changes():
    patch = (
        "diff --git a/.github/workflows/unsafe.yml b/.github/workflows/unsafe.yml\n"
        "--- a/.github/workflows/unsafe.yml\n"
        "+++ b/.github/workflows/unsafe.yml\n"
    )
    try:
        validate_patch(patch)
    except RuntimeError as exc:
        assert "forbidden path" in str(exc)
    else:
        raise AssertionError("workflow patch should be rejected")
