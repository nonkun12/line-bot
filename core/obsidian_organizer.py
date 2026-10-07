"""Safety contract for the Obsidian Organizer AI.

The organizer is proposal-only in v1. It may classify Inbox notes and suggest
destination paths, but it must not mutate the vault. Human approval is required
before any move, overwrite, merge, archive, or delete operation.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OrganizerCategory(str, Enum):
    PROJECT = "01_Projects"
    TASK = "02_Tasks"
    DECISION = "03_Decisions"
    KNOWLEDGE = "04_Knowledge"
    LOG = "05_Logs"
    ARCHIVE = "99_Archive"
    INBOX = "00_Inbox"


@dataclass(frozen=True)
class OrganizerProposal:
    source_path: str
    category: OrganizerCategory
    destination_path: str | None
    reason: str
    confidence: float
    requires_human_approval: bool = True
    destructive: bool = False

    def validate(self) -> None:
        if not self.source_path.endswith(".md"):
            raise ValueError("source_path must be a Markdown note")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if not self.requires_human_approval:
            raise ValueError("human approval is mandatory in v1")
        if self.destructive:
            raise ValueError("destructive proposals are forbidden in v1")
        if self.destination_path and not self.destination_path.endswith(".md"):
            raise ValueError("destination_path must be a Markdown note")


def classify_text(text: str) -> tuple[OrganizerCategory, str]:
    """Deterministic safety-first baseline classification.

    This intentionally prefers INBOX when the signal is weak. A future LLM
    organizer may improve the proposal, but it must still return this contract
    and remain proposal-only until a Human/Safety Gate approves it.
    """
    value = str(text or "").strip()
    lowered = value.casefold()

    if any(x in lowered for x in ("todo", "task", "残件", "やること", "次にやる")):
        return OrganizerCategory.TASK, "task/action signal"
    if any(x in lowered for x in ("決定", "decision", "方針", "採用する", "確定")):
        return OrganizerCategory.DECISION, "decision signal"
    if any(x in lowered for x in ("テスト結果", "実行結果", "ログ", "passed", "failed", "sha")):
        return OrganizerCategory.LOG, "execution/log signal"
    if any(x in lowered for x in ("プロジェクト", "project", "開発", "実装", "構築")):
        return OrganizerCategory.PROJECT, "project/development signal"
    if any(x in lowered for x in ("知識", "knowledge", "参考", "調査", "仕様", "説明")):
        return OrganizerCategory.KNOWLEDGE, "knowledge/reference signal"

    return OrganizerCategory.INBOX, "insufficient signal; keep in Inbox"


def make_proposal(source_path: str, text: str) -> OrganizerProposal:
    category, reason = classify_text(text)
    proposal = OrganizerProposal(
        source_path=source_path,
        category=category,
        destination_path=None if category is OrganizerCategory.INBOX
        else f"{category.value}/{source_path.rsplit('/', 1)[-1]}",
        reason=reason,
        confidence=0.75 if category is not OrganizerCategory.INBOX else 0.25,
    )
    proposal.validate()
    return proposal


__all__ = [
    "OrganizerCategory",
    "OrganizerProposal",
    "classify_text",
    "make_proposal",
]
