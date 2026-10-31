from pathlib import Path


def test_distributed_loop_creator_critic_advisory_honors_explicit_opt_in():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "distributed-autonomous-loop.yml"
    )
    source = workflow.read_text(encoding="utf-8")

    assert "SELF_IMPROVEMENT_CREATOR_CRITIC: 'false'" in source
    review = source[
        source.index("- name: Advisory Creator-Critic review for failed or repaired tasks"):
        source.index("- name: Build review-only self-improvement candidate pool")
    ]
    assert review.count("if: always() && env.SELF_IMPROVEMENT_CREATOR_CRITIC == 'true'") == 2
    assert "continue-on-error: true" in review
    assert "AUTO_APPLY_PATCH: 'false'" in source
    assert "AUTO_DEPLOY: 'false'" in source
