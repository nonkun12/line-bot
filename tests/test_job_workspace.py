import os
import subprocess

import job_workspace


def test_workspace_for_job_is_created_and_reused(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "worker@test.local"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "worker-test"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True)

    monkeypatch.setattr(job_workspace, "DEFAULT_WORKTREE_ROOT", ".worker-worktrees")
    first = job_workspace.workspace_for_job(123, repo_root=str(repo))
    second = job_workspace.workspace_for_job(123, repo_root=str(repo))

    assert first == second
    assert os.path.isdir(first)
    assert (os.path.join(first, "README.md"))

    assert job_workspace.remove_workspace(123, repo_root=str(repo)) is True
    assert not os.path.exists(first)
