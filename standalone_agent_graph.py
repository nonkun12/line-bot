"""Import bridge for the hyphenated standalone-agent package directory."""

from __future__ import annotations

import sys
from pathlib import Path


_STANDALONE_DIR = Path(__file__).resolve().parent / "standalone-agent"
if str(_STANDALONE_DIR) not in sys.path:
    sys.path.insert(0, str(_STANDALONE_DIR))

# The main application also has top-level ``agents``/``graph`` packages.
# Purge the whole imported module trees so the worker resolves the standalone
# implementations from the directory above, including nested agent modules.
for _prefix in ("agents", "graph"):
    for _module_name in list(sys.modules):
        if _module_name == _prefix or _module_name.startswith(f"{_prefix}."):
            sys.modules.pop(_module_name, None)

from graph.graph import build_worker_graph  # noqa: E402,F401
