"""Import bridge for the hyphenated standalone-agent package directory."""

from __future__ import annotations

import sys
from pathlib import Path


_STANDALONE_DIR = Path(__file__).resolve().parent / "standalone-agent"
if str(_STANDALONE_DIR) not in sys.path:
    sys.path.insert(0, str(_STANDALONE_DIR))

from graph.graph import build_worker_graph  # noqa: E402,F401
