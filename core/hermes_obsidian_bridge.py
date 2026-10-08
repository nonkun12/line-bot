"""Fail-closed boundary for forwarding verified Hermes results to the Obsidian queue.

This module deliberately has no filesystem, network, GitHub, or Obsidian side effects.
It only decides whether a Hermes result is eligible for a later queue operation.
"""
from __future__ import annotations

from typing import Mapping

PASS_STATUS = "PASS"
ALLOWED_SOURCE = "hermes-kanban"


def is_verified_hermes_result(result: Mapping[str, object]) -> bool:
    """Return True only for an explicitly verified Hermes PASS result."""
    if not isinstance(result, Mapping):
        return False
    if result.get("source") != ALLOWED_SOURCE:
        return False
    if result.get("status") != PASS_STATUS:
        return False
    if result.get("verified") is not True:
        return False
    if result.get("auto_apply_patch") is not False:
        return False
    if result.get("auto_deploy") is not False:
        return False
    return True


__all__ = ["ALLOWED_SOURCE", "PASS_STATUS", "is_verified_hermes_result"]
