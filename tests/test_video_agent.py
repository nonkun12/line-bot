from agents.video.pipeline import (
    VideoPlan,
    VideoProductionPipeline,
    VideoProviderUnavailable,
    VideoScene,
    build_initial_plan,
)


def test_build_initial_plan_creates_bounded_storyboard():
    plan = build_initial_plan(
        "京都の朝。主人公は静かな寺を訪れる。紅葉が風に舞う。",
        title="京都の秋",
    )

    assert isinstance(plan, VideoPlan)
    assert plan.title == "京都の秋"
    assert [scene.scene_id for scene in plan.scenes] == [
        "scene-1", "scene-2", "scene-3"
    ]
    assert all(scene.duration_seconds == 8 for scene in plan.scenes)


def test_pipeline_is_provider_neutral_until_a_provider_is_configured():
    plan = build_initial_plan("朝の街を歩く。")
    pipeline = VideoProductionPipeline()

    requests = pipeline.generation_requests(plan)
    assert len(requests) == 1
    assert requests[0].aspect_ratio == "16:9"
    assert requests[0].scene_id == "scene-1"

    try:
        pipeline.generate(plan)
    except VideoProviderUnavailable:
        pass
    else:
        raise AssertionError("generation must fail closed without a provider")


def test_video_plan_rejects_excessive_scene_duration():
    scenes = tuple(
        VideoScene(
            scene_id=f"scene-{i}",
            narration="narration",
            visual_prompt="visual",
            duration_seconds=60,
        )
        for i in range(1, 12)
    )
    try:
        VideoPlan(
            title="too long",
            source_summary="source",
            scenes=scenes,
        )
    except ValueError as exc:
        assert "duration" in str(exc)
    else:
        raise AssertionError("duration limit must be enforced")
