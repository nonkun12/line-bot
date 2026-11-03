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
        "shot_list", "audio_plan", "production_readiness",
    ]
    assert by_id["storyboard"]["depends_on"] == ["continuity_review"]
    assert set(by_id["production_readiness"]["depends_on"]) == {"shot_list", "audio_plan"}


def test_scenario_validator_detects_duration_tampering():
    draft = build_scenario("小さな冒険", duration_seconds=60, scene_count=3)
    draft["scenes"][0]["duration_seconds"] += 1
    assert "scene_duration_total_mismatch" in validate_scenario(draft)
