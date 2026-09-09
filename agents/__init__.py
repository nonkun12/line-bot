"""Shared root agents package.

The repository contains legacy/root agents plus the autonomous Worker agents
under ``standalone-agent/agents``. Extend the package search path so both sets
of subpackages can coexist without import-order hacks in CI.
"""

from pathlib import Path

_worker_agents = Path(__file__).resolve().parent.parent / "standalone-agent" / "agents"
if _worker_agents.is_dir():
    __path__.append(str(_worker_agents))
