from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import pytest

from core.agent_parallel_worktrees import IsolatedParallelBatchRunner
from core.agent_worktree import IsolatedWorktreeManager
from core.multi_agent import AgentResult, AgentRole, AgentTask


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return result.stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, str, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, timeout=15)
    git(repo, "config", "user.name", "Parallel Runner Tests")
    git(repo, "config", "user.email", "parallel-runner-tests@example.invalid")
    (repo / "README.md").write_text("base\\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "initial")
    return repo, git(repo, "rev-parse", "HEAD"), tmp_path / "workers"


def task(task_id: str, resources: frozenset[str], deps: tuple[str, ...] = ()) -> AgentTask:
    return AgentTask(task_id, AgentRole.IMPLEMENTER, f"work on {task_id}", resources, deps)


class AcceptGate:
    def verify(self, task: AgentTask, result: AgentResult, worktree_path: Path) -> bool:
        return worktree_path.is_dir() and result.task_id == task.task_id


def test_independent_tasks_run_in_distinct_worktrees_concurrently(repository):
    repo, commit, root = repository
    barrier = threading.Barrier(2)
    paths: dict[str, Path] = {}
    paths_lock = threading.Lock()

    class Executor:
        def execute_in_worktree(self, item: AgentTask, path: Path) -> AgentResult:
            with paths_lock:
                paths[item.task_id] = path
            barrier.wait(timeout=5)
            (path / f"{item.task_id}.txt").write_text(item.task_id, encoding="utf-8")
            return AgentResult(item.task_id, True, "done")

    runner = IsolatedParallelBatchRunner(
        IsolatedWorktreeManager(repo, root), Executor(), AcceptGate(),
        base_ref=commit, max_workers=2,
    )
    report = runner.run([task("worker-a", frozenset({"src/a.py"})),
                         task("worker-b", frozenset({"src/b.py"}))])

    assert report.success
    assert report.batches_completed == 1
    assert set(paths) == {"worker-a", "worker-b"}
    assert paths["worker-a"] != paths["worker-b"]
    assert (paths["worker-a"] / "worker-a.txt").read_text() == "worker-a"
    assert (paths["worker-b"] / "worker-b.txt").read_text() == "worker-b"
    assert git(repo, "rev-parse", "HEAD") == commit


def test_failed_batch_stops_dependent_work_and_preserves_worktrees(repository):
    repo, commit, root = repository
    calls: list[str] = []

    class Executor:
        def execute_in_worktree(self, item: AgentTask, path: Path) -> AgentResult:
            calls.append(item.task_id)
            if item.task_id == "first":
                (path / "diagnostic.txt").write_text("preserve", encoding="utf-8")
                return AgentResult(item.task_id, False, "test gate failed")
            return AgentResult(item.task_id, True, "ok")

    runner = IsolatedParallelBatchRunner(
        IsolatedWorktreeManager(repo, root), Executor(), AcceptGate(),
        base_ref=commit, max_workers=2,
    )
    report = runner.run([
        task("first", frozenset({"src/a.py"})),
        task("second", frozenset({"src/b.py"}), ("first",)),
    ])

    assert not report.success
    assert report.failed_task_id == "first"
    assert "second" not in calls
    assert (root / "first" / "diagnostic.txt").read_text() == "preserve"
    assert report.batches_completed == 0


def test_safety_gate_rejection_fails_closed(repository):
    repo, commit, root = repository

    class Executor:
        def execute_in_worktree(self, item: AgentTask, path: Path) -> AgentResult:
            (path / "unsafe.txt").write_text("out of scope", encoding="utf-8")
            return AgentResult(item.task_id, True, "claimed success")

    class RejectGate:
        def verify(self, task: AgentTask, result: AgentResult, worktree_path: Path) -> bool:
            return False

    runner = IsolatedParallelBatchRunner(
        IsolatedWorktreeManager(repo, root), Executor(), RejectGate(),
        base_ref=commit,
    )
    report = runner.run([task("unsafe", frozenset({"src/a.py"}))])

    assert not report.success
    assert report.failed_task_id == "unsafe"
    assert "safety gate rejected" in (report.error or "")
    assert (root / "unsafe" / "unsafe.txt").exists()


@pytest.mark.parametrize("max_workers", [0, -1, 5, True])
def test_worker_limit_is_validated(repository, max_workers):
    repo, commit, root = repository

    with pytest.raises(ValueError, match="between 1 and 4"):
        IsolatedParallelBatchRunner(
            IsolatedWorktreeManager(repo, root), object(), AcceptGate(),
            base_ref=commit, max_workers=max_workers,
        )


def test_safety_gate_is_mandatory(repository):
    repo, commit, root = repository

    with pytest.raises(ValueError, match="safety gate is required"):
        IsolatedParallelBatchRunner(
            IsolatedWorktreeManager(repo, root), object(), None,
            base_ref=commit,
        )


def test_bad_executor_result_fails_closed(repository):
    repo, commit, root = repository

    class Executor:
        def execute_in_worktree(self, item: AgentTask, path: Path) -> object:
            return "not an AgentResult"

    runner = IsolatedParallelBatchRunner(
        IsolatedWorktreeManager(repo, root), Executor(), AcceptGate(),
        base_ref=commit,
    )
    report = runner.run([task("bad-result", frozenset({"src/a.py"}))])

    assert not report.success
    assert report.failed_task_id == "bad-result"
    assert "AgentResult" in (report.error or "")
    assert (root / "bad-result").is_dir()



def test_actual_changed_path_collision_fails_batch_closed(repository):
    repo, commit, root = repository

    class Executor:
        def execute_in_worktree(self, item: AgentTask, path: Path) -> AgentResult:
            (path / "shared.txt").write_text(item.task_id, encoding="utf-8")
            return AgentResult(item.task_id, True, "done")

    runner = IsolatedParallelBatchRunner(
        IsolatedWorktreeManager(repo, root), Executor(), AcceptGate(),
        base_ref=commit, max_workers=2,
    )
    report = runner.run([
        task("collision-a", frozenset({"src/a.py"})),
        task("collision-b", frozenset({"src/b.py"})),
    ])

    assert not report.success
    assert report.failed_task_id == "collision-b"
    assert "actual changed-path conflict with collision-a: shared.txt" in (report.error or "")
    assert (root / "collision-a" / "shared.txt").exists()
    assert (root / "collision-b" / "shared.txt").exists()


def test_empty_task_list_is_a_successful_noop(repository):
    repo, commit, root = repository

    class Executor:
        def execute_in_worktree(self, item: AgentTask, path: Path) -> AgentResult:
            raise AssertionError("executor must not run for an empty task list")

    runner = IsolatedParallelBatchRunner(
        IsolatedWorktreeManager(repo, root), Executor(), AcceptGate(),
        base_ref=commit,
    )
    report = runner.run([])

    assert report.success
    assert report.outcomes == ()
    assert report.batches_completed == 0


def test_changed_path_parser_handles_rename_with_spaces(repository):
    repo, _commit, _root = repository
    old_path = repo / "README.md"
    new_path = repo / "renamed file.txt"
    old_path.rename(new_path)
    git(repo, "add", "-A")

    changed = IsolatedParallelBatchRunner._changed_paths(repo)

    assert changed == ("README.md", "renamed file.txt")


def test_changed_path_parser_handles_newlines_in_untracked_filename(repository):
    repo, _commit, _root = repository
    unusual_name = "report\nwith-newline.txt"
    (repo / unusual_name).write_text("untracked", encoding="utf-8")

    changed = IsolatedParallelBatchRunner._changed_paths(repo)

    assert changed == (unusual_name,)


def test_actual_parent_child_path_collision_fails_batch_closed(repository):
    repo, commit, root = repository

    class Executor:
        def execute_in_worktree(self, item: AgentTask, path: Path) -> AgentResult:
            if item.task_id == "a-parent-path":
                (path / "shared").write_text("file", encoding="utf-8")
            else:
                nested = path / "shared"
                nested.mkdir()
                (nested / "child.txt").write_text("child", encoding="utf-8")
            return AgentResult(item.task_id, True, "done")

    runner = IsolatedParallelBatchRunner(
        IsolatedWorktreeManager(repo, root), Executor(), AcceptGate(),
        base_ref=commit, max_workers=2,
    )
    report = runner.run([
        task("a-parent-path", frozenset({"src/a.py"})),
        task("z-child-path", frozenset({"src/b.py"})),
    ])

    assert not report.success
    assert report.failed_task_id == "z-child-path"
    assert "actual changed-path conflict with a-parent-path: shared/child.txt" in (report.error or "")
    assert (root / "a-parent-path" / "shared").is_file()
    assert (root / "z-child-path" / "shared" / "child.txt").is_file()


def test_dependency_batch_with_unintegrated_changes_stops_stale_followup(repository):
    repo, commit, root = repository
    calls: list[str] = []

    class Executor:
        def execute_in_worktree(self, item: AgentTask, path: Path) -> AgentResult:
            calls.append(item.task_id)
            (path / "implementation.txt").write_text(item.task_id, encoding="utf-8")
            return AgentResult(item.task_id, True, "done")

    runner = IsolatedParallelBatchRunner(
        IsolatedWorktreeManager(repo, root), Executor(), AcceptGate(),
        base_ref=commit, max_workers=2,
    )
    report = runner.run([
        task("phase-one", frozenset({"src/a.py"})),
        task("phase-two", frozenset({"src/b.py"}), ("phase-one",)),
    ])

    assert not report.success
    assert report.failed_task_id is None
    assert "unintegrated changes" in (report.error or "")
    assert calls == ["phase-one"]
    assert report.batches_completed == 1
    assert (root / "phase-one" / "implementation.txt").exists()
    assert not (root / "phase-two").exists()
