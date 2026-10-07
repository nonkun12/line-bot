from core.obsidian_organizer import (
    OrganizerCategory,
    make_proposal,
)


def test_weak_note_stays_in_inbox():
    proposal = make_proposal("note.md", "今日は少し考えたことを書いた")
    assert proposal.category is OrganizerCategory.INBOX
    assert proposal.destination_path is None
    assert proposal.requires_human_approval is True
    assert proposal.destructive is False


def test_task_note_gets_task_proposal():
    proposal = make_proposal("note.md", "残件: ObsidianのiPhone同期を確認する")
    assert proposal.category is OrganizerCategory.TASK
    assert proposal.destination_path == "02_Tasks/note.md"


def test_decision_note_gets_decision_proposal():
    proposal = make_proposal("note.md", "方針: iCloudは使わない")
    assert proposal.category is OrganizerCategory.DECISION
    assert proposal.destination_path == "03_Decisions/note.md"


def test_log_note_gets_log_proposal():
    proposal = make_proposal("note.md", "分散Loop test passed, SHA abc123")
    assert proposal.category is OrganizerCategory.LOG
    assert proposal.destination_path == "05_Logs/note.md"


def test_proposal_is_never_destructive():
    proposal = make_proposal("note.md", "残件: 整理する")
    proposal.validate()
    assert proposal.destructive is False
    assert proposal.requires_human_approval is True
