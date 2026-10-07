# Obsidian Organizer AI — v1

## Purpose

Reduce the accumulation of unstructured notes without allowing an AI to silently delete, overwrite, merge, or move important notes.

## v1 flow

LINE → MCP → Mac → 00_Inbox/ → Organizer AI → proposal → Safety Gate → Human approval → vault mutation

## Categories

- 00_Inbox/: weak/uncertain classification
- 01_Projects/: projects and development
- 02_Tasks/: actionable items
- 03_Decisions/: confirmed decisions and policies
- 04_Knowledge/: durable reference/knowledge
- 05_Logs/: execution/test/work logs
- 99_Archive/: completed/retired material

## Hard safety rules

1. v1 is proposal-only.
2. Human approval is mandatory.
3. Delete is forbidden.
4. Overwrite is forbidden.
5. Merge is forbidden.
6. Bulk moves are forbidden.
7. Low-confidence notes remain in Inbox.
8. Every approved mutation must have an audit record and rollback path.
9. A failed Safety Gate stops the operation; there is no fallback mutation path.

The current implementation in core/obsidian_organizer.py is intentionally a small contract and deterministic baseline. The LLM-powered classifier and the Mac vault executor are separate follow-up steps so that adding the AI cannot silently gain filesystem mutation authority.
