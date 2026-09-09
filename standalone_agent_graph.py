"""Import bridge for the hyphenated standalone-agent package directory."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


_STANDALONE_DIR = Path(__file__).resolve().parent / "standalone-agent"

# The standalone worker uses absolute top-level imports such as ``graph.*`` and
# ``agents.*``. During the full repository test run the legacy root packages
# may already be imported, so force the standalone directory to the front and
# unload conflicting package modules before importing the worker graph.
try:
    sys.path.remove(str(_STANDALONE_DIR))
except ValueError:
    pass
sys.path.insert(0, str(_STANDALONE_DIR))

for _prefix in ("agents", "graph", "dev_notes"):
    for _module_name in list(sys.modules):
        if _module_name == _prefix or _module_name.startswith(f"{_prefix}."):
            sys.modules.pop(_module_name, None)

# Clear cached import finders so the new path ordering is honored.
for _path in list(sys.path_importer_cache):
    if _path == str(_STANDALONE_DIR) or _path == str(_STANDALONE_DIR.parent):
        sys.path_importer_cache.pop(_path, None)

_worker_graph_module = importlib.import_module("graph.graph")

# Re-export the worker graph module's public test/worker entry points.
def build_graph(*args, **kwargs):
    """Build the worker graph while preserving bridge-level monkeypatching."""
    _worker_graph_module.supervisor_node = supervisor_node
    _worker_graph_module.route_from_supervisor = route_from_supervisor
    return _worker_graph_module.build_graph(*args, **kwargs)


def build_worker_graph(*args, **kwargs):
    return _worker_graph_module.build_worker_graph(*args, **kwargs)


route_from_start = _worker_graph_module.route_from_start
route_from_test = _worker_graph_module.route_from_test
route_from_debug = _worker_graph_module.route_from_debug
route_from_commit = _worker_graph_module.route_from_commit
route_from_publish = _worker_graph_module.route_from_publish
route_from_review = _worker_graph_module.route_from_review
route_from_merge = _worker_graph_module.route_from_merge
supervisor_node = _worker_graph_module.supervisor_node
route_from_supervisor = _worker_graph_module.route_from_supervisor

# Keep access to the actual worker graph module for diagnostics/tests.
graph_module = _worker_graph_module
