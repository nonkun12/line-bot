from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "distributed-autonomous-loop.yml"


def test_distributed_loop_has_independent_fail_closed_publish_gate():
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("- name: Publish verified development branch")
    end = text.index("- name: Persist completed task state", start)
    publish = text[start:end]

    assert "if: success()" in publish
    assert "/tmp/minimal-autonomous-loop.jsonl" in publish
    assert 'row.get("status") not in {"PASS", "NO_CHANGE"}' in publish
    assert 'row.get("exit_code") != 0' in publish
    assert 'rows[-1]["produced_sha"] != final_head' in publish
    assert 'previous["produced_sha"] != current["base_sha"]' in publish
    assert 'rows[0]["base_sha"] != os.environ.get("GITHUB_SHA")' in publish
    assert 'git merge-base --is-ancestor "$GITHUB_SHA" "$head"' in publish
    assert 'task_by_id = {' in publish
    assert 'git", "diff", "--no-renames", "--name-only"' in publish
    assert 'set(diff) - set(allowed)' in publish
    assert 'task changed paths outside its allowlist' in publish


def test_distributed_loop_never_publishes_no_run_or_held_outcomes():
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("- name: Publish verified development branch")
    end = text.index("- name: Persist completed task state", start)
    publish = text[start:end]

    assert "/tmp/autonomous-loop-not-run" in publish
    assert "/tmp/autonomous-loop-held-tasks" in publish
    assert 'if [ "$head" != "$GITHUB_SHA" ]' in publish
    assert 'echo "::error::Task evidence is missing; refusing publication."' in publish
