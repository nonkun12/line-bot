import re

import db
import goal_intake
import goal_job_store


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", str(tmp_path / "goal-intake.sqlite"))
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U-owner")
    db.init_db()
    goal_job_store.init_goal_job_store()


def test_non_goal_read_only_message_does_not_enter_goal_flow():
    assert goal_intake.handle_goal_intake("U-owner", "Loopの状態を教えて") is None
    assert goal_intake.handle_goal_intake("U-owner", "音楽制作のアイデアを教えて") is None


def test_goal_proposal_is_inert_until_owner_approval(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    reply = goal_intake.handle_goal_intake("U-owner", "Goal: オリジナルゲームを完成させる")
    match = re.search(r"(goal-[a-f0-9]{16})", reply)
    assert match
    goal_id = match.group(1)
    assert goal_job_store.get_goal(goal_id) is None
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT status FROM goal_intake_proposals WHERE proposal_id=?", (goal_id,)
        ).fetchone()
    assert row[0] == "pending"


def test_only_allowlisted_owner_can_approve_and_job_is_bounded(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    reply = goal_intake.handle_goal_intake("U-owner", "目標: 音楽と映像からゲームを完成させる")
    goal_id = re.search(r"(goal-[a-f0-9]{16})", reply).group(1)

    denied = goal_intake.handle_goal_intake("U-other", f"Goal承認 {goal_id}")
    assert "権限" in denied
    assert goal_job_store.get_goal(goal_id) is None

    approved = goal_intake.handle_goal_intake("U-owner", f"Goal承認 {goal_id}")
    assert "Sprint計画JOB" in approved
    record = goal_job_store.get_goal(goal_id)
    assert record is not None
    assert record["autonomy_grant"]["max_jobs"] == 1
    assert record["autonomy_grant"]["allowed_path_prefixes"] == ["docs/"]
    assert record["autonomy_grant"]["auto_merge"] is False
    assert record["autonomy_grant"]["auto_deploy"] is False
    assert record["goal"]["jobs"][0]["allowed_paths"] == [f"docs/goal_sprints/{goal_id}.md"]
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT status FROM goal_intake_proposals WHERE proposal_id=?", (goal_id,)
        ).fetchone()
        jobs = conn.execute(
            "SELECT COUNT(*) FROM goal_chain_jobs WHERE goal_id=?", (goal_id,)
        ).fetchone()[0]
    assert row[0] == "approved"
    assert jobs == 1


def test_approval_is_idempotent(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    reply = goal_intake.handle_goal_intake("U-owner", "Goal: Sprint方式で開発する")
    goal_id = re.search(r"(goal-[a-f0-9]{16})", reply).group(1)
    first = goal_intake.handle_goal_intake("U-owner", f"Goal承認 {goal_id}")
    second = goal_intake.handle_goal_intake("U-owner", f"Goal承認 {goal_id}")
    assert "承認し" in first
    assert "既に承認済み" in second
    with db.get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM goal_chain_jobs WHERE goal_id=?", (goal_id,)
        ).fetchone()[0]
    assert count == 1
