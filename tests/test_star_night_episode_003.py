import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "docs" / "creative-worlds" / "star-night"

def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))

def test_episode_003_timeline_is_contiguous_and_30_seconds():
    episode = load("episode-003.json")
    scenes = episode["scenes"]
    assert [s["id"] for s in scenes] == ["SC01", "SC02", "SC03", "SC04", "SC05"]
    assert scenes[0]["start"] == 0
    assert all(a["start"] + a["duration"] == b["start"] for a, b in zip(scenes, scenes[1:]))
    assert sum(s["duration"] for s in scenes) == 30
    assert scenes[-1]["start"] + scenes[-1]["duration"] == 30

def test_episode_003_has_three_prior_route_clues():
    variants = load("episode-003.json")["scenes"][1]["variants"]
    assert {v["when"] for v in variants} == {"CHOICE_E002_MEMORY", "CHOICE_E002_LIGHTS", "CHOICE_E002_TRUST"}
    assert len({v["clue_id"] for v in variants}) == 3

def test_episode_003_choice_ids_are_unique_and_exclusive():
    scene = next(s for s in load("episode-003.json")["scenes"] if s["id"] == "SC04")
    assert scene["exclusive"] is True
    choices = scene["choices"]
    assert [c["id"] for c in choices] == ["CHOICE_E003_RECORD", "CHOICE_E003_TRACE", "CHOICE_E003_SHARE"]
    assert len({c["unlock"] for c in choices}) == 3

def test_three_episode_critic_does_not_claim_independent_execution_or_pass():
    critic = load("continuity-review-e001-e003.json")
    assert critic["status"] == "HOLD"
    assert critic["independent_agent_execution"] is False
    assert critic["canon_change"] is False
    assert critic["publication_authorized"] is False
    assert {f["id"] for f in critic["findings"] if f["severity"] == "HOLD"} == {"CONT-005"}
    assert {f["id"] for f in critic["findings"] if f["severity"] == "PASS"} == {"CONT-004"}

def test_project_registers_episode_003():
    project = load("project.json")
    assert "docs/creative-worlds/star-night/episode-003.md" in project["episode_refs"]
    assert "docs/creative-worlds/star-night/episode-003.json" in project["episode_data_refs"]


def test_episode_001_short_film_and_game_are_separate_adaptation_tracks():
    boundary = load("adaptation-boundary.json")
    assert boundary["tracks"]["short_film"]["canon_scope"] == "short_film_cut_only"
    game = boundary["tracks"]["interactive_game"]
    assert game["canon_scope"] == "interactive_adaptation_only"
    assert len(game["option_ids"]) == 3
    assert any("Never apply" in rule for rule in boundary["cross_track_rules"])

def test_lumina_ledger_blocks_unverified_gameplay_balance():
    ledger = load("lumina-resource-ledger.json")
    assert ledger["status"] == "HOLD_UNVERIFIED_BASELINE"
    assert ledger["gameplay_execution_enabled"] is False
    assert ledger["adaptation_tracks"]["interactive_game"]["episode_001_cost"] is None
    assert ledger["adaptation_tracks"]["interactive_game"]["episode_002_declared_available_output"] == 1
    assert ledger["canon_update_authorized"] is False
    assert ledger["publication_authorized"] is False

def test_continuity_review_only_closes_adaptation_boundary():
    review = load("continuity-review-e001-e003.json")
    findings = {item["id"]: item["severity"] for item in review["findings"]}
    assert findings["CONT-004"] == "PASS"
    assert findings["CONT-005"] == "HOLD"
    assert review["status"] == "HOLD"
