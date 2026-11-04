import db
import goal_job_line_intake as intake
import goal_job_store


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
    assert intake.parse_goal_approval(f"Goal承認 {proposal['proposal_id']}") == proposal["proposal_id"]

    result = intake.approve_goal_proposal("U-authorized", proposal["proposal_id"])
    assert result["decision"] == "CHILD_JOB_QUEUED"
    assert result["job_id"] is not None
    goal = goal_job_store.get_goal(proposal["goal_id"])
    assert goal is not None
    assert goal["autonomy_grant"]["approved_by"] == "U-authorized"
    assert goal["autonomy_grant"]["allowed_path_prefixes"] == ["docs/"]
    children = goal_job_store.get_goal_child_jobs(proposal["goal_id"])
    assert len(children) == 1
    assert children[0]["status"] == "pending"


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
    assert first["job_id"] == second["goal_id"] if False else first["goal_id"] == second["goal_id"]
    assert second["already_approved"] is True
    assert len(goal_job_store.get_goal_child_jobs(proposal["goal_id"])) == 1


def test_read_only_message_is_not_routed_to_goal_flow(tmp_path, monkeypatch):
    _init_db(tmp_path, monkeypatch)
    handled, reply = intake.handle_goal_line_message("U-user", "今のGoalの状態を教えて")
    assert handled is False
    assert reply is None
