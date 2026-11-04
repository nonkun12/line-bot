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
    assert "scene_2_start_time_invalid" in validate_scenario(draft)


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


def test_scenario_rejects_more_scenes_than_available_seconds():
    try:
        build_scenario("短い映像", duration_seconds=15, scene_count=20)
    except ValueError as exc:
        assert "at least scene_count" in str(exc)
    else:
        raise AssertionError("zero-duration scenes must be rejected")


def test_scenario_music_energy_tracks_the_four_act_emotional_arc():
    draft = build_scenario("感情の起伏", duration_seconds=120, scene_count=4)
    assert [scene["music_sync"]["energy"] for scene in draft["scenes"]] == [
        "low", "medium", "high", "low"
    ]


def test_scenario_validator_rejects_bad_start_time_energy_and_motif():
    draft = build_scenario("検証", duration_seconds=120, scene_count=4)
    draft["scenes"][1]["time_start_seconds"] += 1
    draft["scenes"][2]["music_sync"]["energy"] = ["high"]
    draft["scenes"][0]["music_sync"]["motif"] = None
    errors = validate_scenario(draft)
    assert "scene_2_start_time_invalid" in errors
    assert "scene_3_energy_invalid" in errors
    assert "scene_1_motif_invalid" in errors


def test_scenario_validator_rejects_non_string_energy_without_crashing():
    draft = build_scenario("不正な入力", duration_seconds=60, scene_count=3)
    draft["scenes"][0]["music_sync"]["energy"] = ["low"]
    assert "scene_1_energy_invalid" in validate_scenario(draft)


def test_scenario_contains_concrete_editable_screenplay_and_shot_direction():
    draft = build_scenario(
        "星明かりの下で再会する二人",
        premise="離れて暮らした二人が小さな駅で再会する",
        duration_seconds=120,
        scene_count=4,
    )
    scenes = draft["scenes"]
    assert all(scene["dialogue_or_narration"] for scene in scenes)
    assert all(scene["action"] and scene["visual_direction"] for scene in scenes)
    assert all(scene["shot_plan"]["camera_motion"] for scene in scenes)
    assert "星明かり" in scenes[0]["shot_plan"]["focal_subject"]
    assert scenes[0]["shot_plan"]["shot_size"] == "wide_to_medium"
    assert scenes[2]["shot_plan"]["camera_motion"] == "decisive_reveal"
    assert len(scenes[1]["music_sync"]["sync_points"]) == 3
    assert draft["creative_assumptions"]
    assert validate_scenario(draft) == ()


def test_scenario_validator_rejects_missing_shot_plan():
    draft = build_scenario("短い物語", duration_seconds=60, scene_count=3)
    draft["scenes"][1]["shot_plan"]["camera_motion"] = ""
    assert "scene_2_shot_plan_invalid" in validate_scenario(draft)


def test_storyboard_and_shot_list_are_generated_from_scenario():
    from agents.video.storyboard import build_storyboard
    from agents.video.shot_list import build_shot_list

    scenario = build_scenario(
        "星明かりの下で再会する二人",
        premise="離れて暮らした二人が小さな駅で再会する",
        duration_seconds=60,
        scene_count=4,
    )
    storyboard = build_storyboard(scenario)
    shot_list = build_shot_list(storyboard)
    assert storyboard["schema_version"] == "video-storyboard.v1"
    assert len(storyboard["panels"]) == 4
    assert shot_list["schema_version"] == "video-shot-list.v1"
    assert shot_list["duration_seconds"] == 60
    assert shot_list["shots"][0]["start_seconds"] == 0
    assert shot_list["shots"][-1]["end_seconds"] == 60
    assert all(shot["asset_status"] == "needs_rights_cleared_asset" for shot in shot_list["shots"])
    assert shot_list["external_assets_downloaded"] is False


def test_video_agent_returns_storyboard_and_shot_list_with_scenario():
    from agents.video.node import VideoAgent
    from core.agents import AgentRequest

    response = VideoAgent().handle(AgentRequest(
        "user-1", "シナリオを作って",
        metadata={"duration_seconds": 90, "scene_count": 3},
    ))
    assert len(response.metadata["storyboard"]["panels"]) == 3
    assert response.metadata["shot_list"]["duration_seconds"] == 90
    assert "ショット設計" in response.text


def test_storyboard_rejects_invalid_scenario_and_shot_list_rejects_incomplete_panel():
    from agents.video.storyboard import build_storyboard
    from agents.video.shot_list import build_shot_list

    try:
        build_storyboard({})
    except ValueError:
        pass
    else:
        raise AssertionError("invalid scenario must not produce a storyboard")

    try:
        build_shot_list({"schema_version": "video-storyboard.v1", "panels": [{}]})
    except ValueError:
        pass
    else:
        raise AssertionError("incomplete panel must not produce a shot list")


def test_shot_list_rejects_non_contiguous_storyboard_timeline():
    from agents.video.storyboard import build_storyboard
    from agents.video.shot_list import build_shot_list

    scenario = build_scenario("時を越える手紙", duration_seconds=60, scene_count=3)
    storyboard = build_storyboard(scenario)
    storyboard["panels"][1]["time_start_seconds"] += 1
    try:
        build_shot_list(storyboard)
    except ValueError as exc:
        assert "contiguous timeline" in str(exc)
    else:
        raise AssertionError("shot list must reject storyboard timeline gaps")
