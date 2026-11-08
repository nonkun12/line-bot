from pathlib import Path

from scripts.autonomous_task_target_allowlist import TARGETS


def test_allowlist_contains_only_existing_paired_core_and_test_files():
    root = Path(__file__).resolve().parents[1]
    assert len(TARGETS) == 107
    assert len(TARGETS) == len(set(TARGETS))
    assert len({source for source, _ in TARGETS}) == len(TARGETS)
    assert len({test for _, test in TARGETS}) == len(TARGETS)
    for source, test in TARGETS:
        assert source.startswith(("core/", "scripts/", "agents/")) and source.endswith(".py")
        assert test.startswith("tests/test_") and test.endswith(".py")
        assert (root / source).is_file()
        assert (root / test).is_file()


def test_all_candidate_pipeline_stages_use_the_same_allowlist():
    root = Path(__file__).resolve().parents[1]
    modules = (
        "scripts/catalog_exhaustion_analyzer.py",
        "scripts/autonomous_task_issue_drafts.py",
        "scripts/catalog_exhaustion_candidate_adapter.py",
        "scripts/register_approved_task_candidate.py",
    )
    for module in modules:
        source = (root / module).read_text(encoding="utf-8")
        assert "from scripts.autonomous_task_target_allowlist import TARGETS" in source

def test_allowlist_includes_task_lifecycle_and_recovery_discovery_pairs():
    expected = {
        ("scripts/autonomous_task_refill.py", "tests/test_autonomous_task_refill.py"),
        ("scripts/autonomous_task_proposals.py", "tests/test_autonomous_task_proposals.py"),
        ("scripts/catalog_exhaustion_analyzer.py", "tests/test_catalog_exhaustion_analyzer.py"),
        ("scripts/distributed_loop_queue_progress.py", "tests/test_distributed_loop_queue_progress.py"),
        ("scripts/recovery_ai.py", "tests/test_recovery_ai.py"),
        ("scripts/resume_held_task.py", "tests/test_resume_held_task.py"),
        ("scripts/should_continue_distributed_loop.py", "tests/test_should_continue_distributed_loop.py"),
        ("scripts/work_finder_ai.py", "tests/test_work_finder_ai.py"),
        ("scripts/line_development_worker_v2.py", "tests/test_line_development_worker_v2.py"),
    }
    assert expected.issubset(set(TARGETS))
