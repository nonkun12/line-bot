from core.protected_paths import is_protected

def test_control_plane_paths_are_protected():
    for path in (
        "core/execution_safety.py",
        "core/quality_runtime.py",
        "core/control_tower.py",
        "core/agent_runtime.py",
        "core/self_improvement_policy.py",
        "core/management_safety.py",
        "scripts/run_guarded_runtime.py",
        "scripts/nightly_worker.py",
        "slack_command.py",
        "app.py",
        "requirements.txt",
    ):
        assert is_protected(path), path

def test_workflow_and_git_paths_are_protected():
    assert is_protected(".github/workflows/anything.yml")
    assert is_protected(".git/config")

def test_normal_application_file_is_not_protected():
    assert not is_protected("core/management_router.py")


def test_protected_directory_manifests_and_ancestors_are_rejected():
    for path in (".github/", ".github", "secrets/", ".git/", "core", "."):
        assert is_protected(path), path
