import json
from datetime import datetime, timezone

import db
import goal_job_orchestrator
import goal_job_line_intake as intake
import goal_job_store
from agents.media.local_executor import EXECUTOR_ID, execute_local_media_job


def _init_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", str(tmp_path / "goal-line-intake.sqlite"))
    db.init_db()
    goal_job_store.init_goal_job_store()
    intake.init_goal_line_intake()


def test_only_explicit_goal_prefix_is_classified():
    assert intake.parse_goal_intake("Goal: Build an original game") == "Build an original game"
    assert intake.parse_goal_intake("目標：音楽と映像からゲームを作る") == "音楽と映像からゲームを作る"
    assert intake.parse_goal_intake("今日は天気を教えて") is None
    assert intake.parse_goal_intake("ゲームの進捗を教えて") is None
    assert intake.parse_goal_approval("Goal承認 abc123") == "abc123"
    assert intake.parse_goal_approval("Goal承認 abc123 extra") is None


def test_goal_proposal_is_inert_until_same_user_approves(tmp_path, monkeypatch):
    _init_db(tmp_path, monkeypatch)
    monkeypatch.setenv("GOAL_APPROVER_USER_IDS", "U-authorized")
    proposal = intake.create_goal_proposal("U-authorized", "Build an original browser game")
    assert goal_job_store.get_goal(proposal["goal_id"]) is None
    proposal_record = intake._build_proposal("Build an original browser game", proposal["proposal_id"])
    assert [job["id"] for job in proposal_record["jobs"]] == [
        "media-01-audiovisual-draft", "sprint-01-music-video", "sprint-02-interactive",
        "sprint-03-game-prototype", "sprint-04-full-game",
    ]
    assert proposal_record["jobs"][1]["depends_on"] == ["media-01-audiovisual-draft"]
    assert proposal_record["jobs"][4]["depends_on"] == ["sprint-03-game-prototype"]
    assert all(job["allowed_paths"][0].startswith("docs/goal-plans/") for job in proposal_record["jobs"])
    assert intake.parse_goal_approval(f"Goal承認 {proposal['proposal_id']}") == proposal["proposal_id"]

    result = intake.approve_goal_proposal("U-authorized", proposal["proposal_id"])
    assert result["decision"] == "CHILD_JOB_QUEUED"
    assert result["job_id"] is not None
    goal = goal_job_store.get_goal(proposal["goal_id"])
    assert goal is not None
    assert goal["goal"]["audiovisual_sprint_plan"]["schema_version"] == "audiovisual-to-game-sprint-plan.v1"
    from agents.media.goal_job_chain_store import get_goal_chain
    media_chain = get_goal_chain("U-authorized", proposal["goal_id"])
    assert media_chain["state"]["ready_job_ids"] == ["scenario"]
    assert goal["autonomy_grant"]["approved_by"] == "U-authorized"
    assert goal["autonomy_grant"]["allowed_path_prefixes"] == ["docs/"]
    children = goal_job_store.get_goal_child_jobs(proposal["goal_id"])
    assert len(children) == 1
    assert children[0]["status"] == "pending"
    persisted = db.get_job(children[0]["job_id"])
    payload = json.loads(persisted["message"])
    assert payload["executor"] == "mac_local_media.v1"
    assert payload["operation"] == "create_audiovisual_bundle"
    assert payload["scenario"]["schema_version"] == "video-scenario.v1"


def test_goal_proposal_cannot_be_approved_by_another_user(tmp_path, monkeypatch):
    _init_db(tmp_path, monkeypatch)
    monkeypatch.setenv("GOAL_APPROVER_USER_IDS", "U-authorized")
    proposal = intake.create_goal_proposal("U-authorized", "Create a music and video workflow")
    try:
        intake.approve_goal_proposal("U-other", proposal["proposal_id"])
    except PermissionError:
        pass
    else:
        raise AssertionError("another LINE user must not approve this proposal")
    assert goal_job_store.get_goal(proposal["goal_id"]) is None


def test_goal_approval_is_idempotent(tmp_path, monkeypatch):
    _init_db(tmp_path, monkeypatch)
    monkeypatch.setenv("GOAL_APPROVER_USER_IDS", "U-authorized")
    proposal = intake.create_goal_proposal("U-authorized", "Create a safe sprint workflow")
    first = intake.approve_goal_proposal("U-authorized", proposal["proposal_id"])
    second = intake.approve_goal_proposal("U-authorized", proposal["proposal_id"])
    assert first["goal_id"] == second["goal_id"]
    assert second["already_approved"] is True
    assert len(goal_job_store.get_goal_child_jobs(proposal["goal_id"])) == 1


def test_read_only_message_is_not_routed_to_goal_flow(tmp_path, monkeypatch):
    _init_db(tmp_path, monkeypatch)
    handled, reply = intake.handle_goal_line_message("U-user", "今のGoalの状態を教えて")
    assert handled is False
    assert reply is None


def test_goal_chain_status_and_human_stage_gates_are_owner_scoped(tmp_path, monkeypatch):
    _init_db(tmp_path, monkeypatch)
    monkeypatch.setenv("GOAL_APPROVER_USER_IDS", "U-authorized")
    proposal = intake.create_goal_proposal("U-authorized", "音楽と映像からゲームを作る")
    intake.approve_goal_proposal("U-authorized", proposal["proposal_id"])

    from agents.media.goal_job_chain_store import (
        get_goal_chain,
        record_goal_chain_evidence,
    )
    chain = get_goal_chain("U-authorized", proposal["goal_id"])
    assert chain["state"]["ready_job_ids"] == ["scenario"]

    handled, reply = intake.handle_goal_line_message(
        "U-authorized", f"Goal状態 {proposal['goal_id']}"
    )
    assert handled is True
    assert "READY: scenario" in reply

    # Only the verified media executor completion can advance the scenario
    # stage; this direct store call represents that durable completion event.
    chain = record_goal_chain_evidence(
        "U-authorized", proposal["goal_id"], expected_version=chain["version"],
        completed_job_ids=["scenario"], event_type="stage_completed",
    )
    assert chain["state"]["awaiting_human_approval_job_ids"] == ["scenario"]

    denied, denied_reply = intake.handle_goal_line_message(
        "U-other", f"Goalステージ承認 {proposal['goal_id']} scenario"
    )
    assert denied is True
    assert "許可されていません" in denied_reply

    approved, approval_reply = intake.handle_goal_line_message(
        "U-authorized", f"Goalステージ承認 {proposal['goal_id']} scenario"
    )
    assert approved is True
    assert "承認しました" in approval_reply

    chain = get_goal_chain("U-authorized", proposal["goal_id"])
    assert chain["state"]["ready_job_ids"] == ["music", "visual"]

    assert intake.handle_goal_line_message(
        "U-authorized", f"Goalステージ承認 {proposal['goal_id']} music"
    )[0] is True
    chain = get_goal_chain("U-authorized", proposal["goal_id"])
    assert chain["state"]["ready_job_ids"] == ["visual"]

    intake.handle_goal_line_message(
        "U-authorized", f"Goalステージ承認 {proposal['goal_id']} visual"
    )
    chain = get_goal_chain("U-authorized", proposal["goal_id"])
    assert chain["state"]["ready_job_ids"] == ["sync"]


def test_goal_stage_approval_cannot_skip_uncompleted_stage(tmp_path, monkeypatch):
    _init_db(tmp_path, monkeypatch)
    monkeypatch.setenv("GOAL_APPROVER_USER_IDS", "U-authorized")
    proposal = intake.create_goal_proposal("U-authorized", "Create original audiovisual game")
    intake.approve_goal_proposal("U-authorized", proposal["proposal_id"])
    handled, reply = intake.handle_goal_line_message(
        "U-authorized", f"Goalステージ承認 {proposal['goal_id']} music"
    )
    assert handled is True
    assert "まだ人間レビュー可能" in reply



def test_approved_goal_runs_four_sequential_sprint_plans_to_goal(tmp_path, monkeypatch):
    _init_db(tmp_path, monkeypatch)
    monkeypatch.setenv("GOAL_APPROVER_USER_IDS", "U-authorized")
    proposal = intake.create_goal_proposal("U-authorized", "Build an original browser game")
    approved = intake.approve_goal_proposal("U-authorized", proposal["proposal_id"])
    assert approved["decision"] == "CHILD_JOB_QUEUED"

    media_job = db.claim_pending_media_goal_child_job(EXECUTOR_ID)
    assert media_job is not None
    media_payload = goal_job_store.authorize_claimed_media_job(
        media_job, EXECUTOR_ID, "create_audiovisual_bundle"
    )
    media_evidence = {
        "checks": [
            {"name": name, "status": "PASS", "source": EXECUTOR_ID}
            for name in (
                "typed_local_executor_authorization",
                "scenario_validation",
                "output_confined_to_configured_root",
                "artifact_inventory_and_sha256",
                "no_publish_or_external_download",
            )
        ],
        "executor": EXECUTOR_ID,
        "goal_job_id": media_job["id"],
        "artifact_sha256": {
            "scenario": "a" * 64, "music_plan": "b" * 64, "midi": "c" * 64,
            "audio_preview": "d" * 64, "video_edit_decision_list": "e" * 64,
        },
        "receipt_sha256": "f" * 64,
    }
    assert goal_job_store.complete_claimed_child_job(
        media_job["id"], media_job["claim_token"], success=True,
        result="verified media draft", evidence=media_evidence,
    )
    goal_job_store.update_goal_evidence(
        proposal["goal_id"],
        goal_job_store.evaluate_completed_goal_criteria(proposal["goal_id"]),
    )

    executed = ["media-01-audiovisual-draft"]

    def executor(_job, payload):
        executed.append(payload["goal_job_key"])
        return {
            "result": f"Created {payload['goal_job_key']} Sprint plan.",
            "evidence": {
                "checks": [{"name": "plan_artifact", "status": "PASS", "source": "test executor"}]
            },
        }

    def evaluator(goal_record, completed_job):
        payload = json.loads(completed_job["message"])
        results = dict(goal_record["criterion_results"])
        results[payload["criterion_id"]] = "PASS"
        return results

    result = goal_job_orchestrator.run_until_blocked(
        proposal["goal_id"],
        executor=executor,
        evidence_evaluator=evaluator,
        max_steps=5,
    )
    assert result["decision"] == "GOAL_ACHIEVED"
    assert executed == [
        "media-01-audiovisual-draft",
        "sprint-01-music-video",
        "sprint-02-interactive",
        "sprint-03-game-prototype",
        "sprint-04-full-game",
    ]
    assert goal_job_store.get_goal(proposal["goal_id"])["status"] == "achieved"


def test_stale_approval_lease_recovers_existing_goal_without_duplicate_job(tmp_path, monkeypatch):
    _init_db(tmp_path, monkeypatch)
    monkeypatch.setenv("GOAL_APPROVER_USER_IDS", "U-authorized")
    proposal = intake.create_goal_proposal("U-authorized", "Build a free original game")
    first = intake.approve_goal_proposal("U-authorized", proposal["proposal_id"])
    assert first["decision"] == "CHILD_JOB_QUEUED"
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE goal_line_proposals SET status='approving',approval_started_at=? WHERE proposal_id=?",
            ("2000-01-01T00:00:00+00:00", proposal["proposal_id"]),
        )
    resumed = intake.approve_goal_proposal("U-authorized", proposal["proposal_id"])
    assert resumed["already_approved"] is True
    assert resumed["decision"] == "HOLD"
    assert resumed["reason"] == "waiting_for_registered_jobs"
    assert len(goal_job_store.get_goal_child_jobs(proposal["goal_id"])) == 1


def test_active_approval_lease_prevents_concurrent_duplicate_approval(tmp_path, monkeypatch):
    _init_db(tmp_path, monkeypatch)
    monkeypatch.setenv("GOAL_APPROVER_USER_IDS", "U-authorized")
    proposal = intake.create_goal_proposal("U-authorized", "Build a safe creative pipeline")
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE goal_line_proposals SET status='approving',approval_started_at=? WHERE proposal_id=?",
            (datetime.now(timezone.utc).isoformat(), proposal["proposal_id"]),
        )
    try:
        intake.approve_goal_proposal("U-authorized", proposal["proposal_id"])
    except ValueError as exc:
        assert "already in progress" in str(exc)
    else:
        raise AssertionError("active approval lease must prevent concurrent approval")


def test_expired_proposal_persists_terminal_expired_status(tmp_path, monkeypatch):
    _init_db(tmp_path, monkeypatch)
    monkeypatch.setenv("GOAL_APPROVER_USER_IDS", "U-authorized")
    proposal = intake.create_goal_proposal("U-authorized", "Build a free audiovisual prototype")
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE goal_line_proposals SET expires_at=? WHERE proposal_id=?",
            ("2000-01-01T00:00:00+00:00", proposal["proposal_id"]),
        )

    try:
        intake.approve_goal_proposal("U-authorized", proposal["proposal_id"])
    except ValueError as exc:
        assert "proposal expired" in str(exc)
    else:
        raise AssertionError("expired proposals must not be approved")

    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT status FROM goal_line_proposals WHERE proposal_id=?",
            (proposal["proposal_id"],),
        ).fetchone()
    assert row == ("expired",)
    assert goal_job_store.get_goal(proposal["goal_id"]) is None
