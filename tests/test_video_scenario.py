from agents.video.scenario import build_scenario, scenario_goal_jobs, validate_scenario


def test_scenario_draft_has_complete_scene_contract_and_exact_duration():
    draft = build_scenario(
        "海辺の小さな町の再生",
        genre="ドキュメンタリー",
        audience="地域の人々",
        duration_seconds=181,
        scene_count=5,
    )
    assert draft["status"] == "draft"
    assert len(draft["scenes"]) == 5
    assert sum(scene["duration_seconds"] for scene in draft["scenes"]) == 181
    assert validate_scenario(draft) == ()
    assert all(scene["continuity"] for scene in draft["scenes"])


def test_scenario_rejects_unbounded_duration_and_scene_count():
    for kwargs in ({"duration_seconds": 0}, {"duration_seconds": 3601},
                   {"scene_count": 1}, {"scene_count": 21}):
        try:
            build_scenario("test", **kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe scenario bounds accepted: {kwargs}")


def test_scenario_goal_jobs_form_dependency_ordered_production_pipeline():
    draft = build_scenario("自然の音を伝える短編", duration_seconds=120, scene_count=4)
    jobs = scenario_goal_jobs(draft)
    by_id = {job["id"]: job for job in jobs}
    assert list(by_id) == [
        "screenplay", "continuity_review", "storyboard",
        "shot_list", "audio_plan", "music_composition",
        "audiovisual_sync_review", "production_readiness",
    ]
    assert by_id["storyboard"]["depends_on"] == ["continuity_review"]
    assert set(by_id["audiovisual_sync_review"]["depends_on"]) == {"shot_list", "music_composition"}
    assert "audiovisual_sync_review" in by_id["production_readiness"]["depends_on"]


def test_scenario_validator_detects_duration_tampering():
    draft = build_scenario("小さな冒険", duration_seconds=60, scene_count=3)
    draft["scenes"][0]["duration_seconds"] += 1
    assert "scene_duration_total_mismatch" in validate_scenario(draft)


def test_video_agent_routes_scenario_request_and_returns_structured_draft():
    from agents.video.node import VideoAgent
    from core.agents import AgentRequest

    agent = VideoAgent()
    request = AgentRequest(
        "user-1",
        "シナリオを作って",
        metadata={"duration_seconds": 90, "scene_count": 3},
    )
    assert agent.can_handle(request)
    response = agent.handle(request)
    assert response.metadata["mode"] == "scenario"
    assert response.metadata["scenario"]["status"] == "draft"
    assert len(response.metadata["scenario"]["scenes"]) == 3
    assert "連続性レビュー" in response.text


def test_video_agent_preserves_existing_script_mode():
    from agents.video.node import VideoAgent
    from core.agents import AgentRequest

    response = VideoAgent().handle(AgentRequest("user-1", "動画の台本を作って"))
    assert response.metadata["mode"] == "script"
    assert response.metadata["scenario"]["schema_version"] == "video-scenario.v1"


def test_scenario_defines_scene_level_music_sync_and_global_harmony():
    draft = build_scenario("夜明けを迎える街", duration_seconds=120, scene_count=4)
    assert draft["audiovisual_direction"]["global_music_motif"]
    assert len(draft["audiovisual_direction"]["emotional_arc"]) == 4
    assert any("クロスフェード" in rule for rule in draft["audiovisual_direction"]["mixing_rules"])
    for scene in draft["scenes"]:
        sync = scene["music_sync"]
        assert sync["cue_in_seconds"] == 0
        assert sync["cue_out_seconds"] == scene["duration_seconds"]
        assert sync["mix_priority"] == "dialogue_first"
        assert sync["sync_points"]


def test_scenario_validator_rejects_music_cue_outside_scene():
    draft = build_scenario("静かな旅", duration_seconds=60, scene_count=3)
    draft["scenes"][1]["music_sync"]["cue_out_seconds"] = 999
    assert "scene_2_music_cue_timing_invalid" in validate_scenario(draft)


def test_scenario_validator_rejects_invalid_sync_point():
    draft = build_scenario("海の記憶", duration_seconds=60, scene_count=3)
    draft["scenes"][0]["music_sync"]["sync_points"][0]["at_seconds"] = -1
    assert "scene_1_sync_points_invalid" in validate_scenario(draft)
