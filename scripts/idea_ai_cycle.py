"""Run one safe, resumable Idea AI cycle from the command line.

This command proposes ideas and persists the cycle locally. It does not invoke
agents, execute experiments, modify project files, or grant execution approval.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.idea_research_cycle import IdeaResearchCycle
from core.idea_research_cycle_store import SQLiteIdeaResearchCycleStore


def run_cycle(focus: str, database: str, namespace: str = "default") -> IdeaResearchCycle:
    store = SQLiteIdeaResearchCycleStore(database)
    saved = store.load(namespace)
    if saved is None:
        cycle = IdeaResearchCycle.start(focus)
        revision = 0
    else:
        if saved.cycle.focus != focus.strip():
            raise ValueError("focus differs from saved cycle; use a new namespace")
        cycle = replace(saved.cycle, ideas=saved.cycle.next_ideas())
        revision = saved.revision
    store.save(namespace, cycle, expected_revision=revision)
    return cycle


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one resumable Idea AI proposal cycle.")
    parser.add_argument("--focus", required=True, help="Development goal for the idea cycle")
    parser.add_argument("--db", required=True, help="Explicit local SQLite database path")
    parser.add_argument("--namespace", default="default", help="Cycle namespace")
    args = parser.parse_args()
    if not args.focus.strip():
        parser.error("--focus must not be empty")

    cycle = run_cycle(args.focus, args.db, args.namespace)
    print(f"Focus: {cycle.focus}")
    print(f"Ideas: {len(cycle.ideas)}")
    for index, idea in enumerate(cycle.ideas, 1):
        print(f"{index}. {idea.title} [{idea.style}]")
        print(f"   {idea.next_step}")
    print("Saved locally. No agents or experiments were executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
