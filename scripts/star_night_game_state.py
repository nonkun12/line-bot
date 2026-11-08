"""Deterministic state transitions for the STAR-NIGHT interactive story."""
from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any, Mapping


class TransitionError(ValueError):
    """Raised when a story choice cannot be applied safely."""


def apply_choice(
    current_node: str,
    state: Mapping[str, Any],
    choice: Mapping[str, Any],
    nodes: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Apply one declared choice and return a new state without mutating inputs.

    State effects are numeric deltas over declared numeric variables. The target
    node must exist, and the choice must originate at the current node.
    """
    if not isinstance(current_node, str) or not current_node:
        raise TransitionError("current_node must be a non-empty string")
    if choice.get("source_node") != current_node:
        raise TransitionError("choice source does not match current node")

    node_by_id = {node.get("id"): node for node in nodes}
    if len(node_by_id) != len(nodes) or any(not key for key in node_by_id):
        raise TransitionError("node ids must be present and unique")

    target = choice.get("next_node")
    if target not in node_by_id:
        raise TransitionError("choice target is not declared")

    effect = choice.get("effect", {})
    if not isinstance(effect, Mapping):
        raise TransitionError("choice effect must be a mapping")

    next_state = deepcopy(dict(state))
    for key, delta in effect.items():
        if key not in next_state:
            raise TransitionError(f"unknown state variable: {key}")
        current = next_state[key]
        if (isinstance(current, bool) or not isinstance(current, (int, float))
                or isinstance(delta, bool) or not isinstance(delta, (int, float))
                or not isfinite(float(current)) or not isfinite(float(delta))):
            raise TransitionError(f"state effect must be finite numeric data: {key}")
        next_value = current + delta
        if not isfinite(float(next_value)):
            raise TransitionError(f"state result must be finite: {key}")
        next_state[key] = next_value

    choice_id = choice.get("id")
    if not isinstance(choice_id, str) or not choice_id:
        raise TransitionError("choice id must be a non-empty string")
    history = list(next_state.get("choice_history", []))
    history.append(choice_id)
    next_state["choice_history"] = history

    discovered = list(next_state.get("discovered_locations", []))
    unlock = node_by_id[target].get("unlocks")
    if unlock and unlock not in discovered:
        discovered.append(unlock)
    next_state["discovered_locations"] = discovered

    return {"current_node": target, "state": next_state}
