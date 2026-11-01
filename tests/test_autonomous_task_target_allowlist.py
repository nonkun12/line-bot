from pathlib import Path

from scripts.autonomous_task_target_allowlist import TARGETS


def test_allowlist_contains_only_existing_paired_core_and_test_files():
    root = Path(__file__).resolve().parents[1]
    assert len(TARGETS) == 63
    assert len(TARGETS) == len(set(TARGETS))
    assert len({source for source, _ in TARGETS}) == len(TARGETS)
    assert len({test for _, test in TARGETS}) == len(TARGETS)
    for source, test in TARGETS:
        assert source.startswith("core/") and source.endswith(".py")
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
