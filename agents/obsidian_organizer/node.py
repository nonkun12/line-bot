"""Proposal-only Obsidian Organizer AI agent.

This agent can classify an explicitly requested note and return a proposal.
It has no vault write capability and never mutates files.
"""
from __future__ import annotations

from core.agents import AgentRequest, AgentResponse
from core.obsidian_organizer import make_proposal


class ObsidianOrganizerAgent:
    name = "obsidian_organizer"
    description = "Proposal-only Obsidian note organizer; human approval required."
    priority = 70
    enabled = True

    def can_handle(self, request: AgentRequest) -> bool:
        message = request.message.strip().casefold()
        return message.startswith(("obsidian整理", "obsidian 整理", "obsidian organize"))

    def handle(self, request: AgentRequest) -> AgentResponse:
        if not self.can_handle(request):
            return AgentResponse(
                text="Obsidian整理の明示的な依頼ではありません。",
                metadata={"success": False, "reason": "intent_rejected"},
            )

        proposal = make_proposal("00_Inbox/note.md", request.message)
        return AgentResponse(
            text=(
                f"整理案: {proposal.category.value}"
                + (f"/{proposal.source_path.rsplit('/', 1)[-1]}" if proposal.destination_path else "")
                + f"。理由: {proposal.reason}。人間の承認が必要です。"
            ),
            metadata={
                "success": True,
                "proposal_only": True,
                "requires_human_approval": proposal.requires_human_approval,
                "destructive": proposal.destructive,
                "category": proposal.category.value,
                "destination_path": proposal.destination_path,
                "confidence": proposal.confidence,
            },
        )


obsidian_organizer_agent = ObsidianOrganizerAgent()

__all__ = ["ObsidianOrganizerAgent", "obsidian_organizer_agent"]
