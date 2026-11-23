"""Proposal-only policy and change governance gates for AI Factory stages 401-405."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _seal(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode("utf-8")).hexdigest()


def check_policy_registry(policies: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 401: require unique policy IDs, versions, and well-formed content digests."""
    errors: list[str] = []
    seen: set[str] = set()
    if not policies:
        errors.append("policies_empty")
    for i, item in enumerate(policies):
        pid, version, digest = item.get("policy_id"), item.get("version"), item.get("content_sha256")
        if not isinstance(pid, str) or not pid.strip():
            errors.append(f"policy_id_invalid:{i}")
        elif pid in seen:
            errors.append(f"policy_id_duplicate:{pid}")
        else:
            seen.add(pid)
        if not isinstance(version, str) or not version.strip():
            errors.append(f"policy_version_missing:{pid if isinstance(pid, str) else i}")
        if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
            errors.append(f"policy_digest_invalid:{pid if isinstance(pid, str) else i}")
    return {"stage": 401, "pass": not errors, "errors": errors,
            "policy_count": len(seen)}


def check_gate_dependency_graph(nodes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 402: require a well-formed acyclic dependency graph with resolved references."""
    errors: list[str] = []
    dependencies: dict[str, list[str]] = {}
    if not nodes:
        errors.append("dependency_nodes_empty")
    for i, item in enumerate(nodes):
        node_id, deps = item.get("node_id"), item.get("depends_on")
        if not isinstance(node_id, str) or not node_id.strip():
            errors.append(f"dependency_node_id_invalid:{i}")
            continue
        if node_id in dependencies:
            errors.append(f"dependency_node_duplicate:{node_id}")
            continue
        if not isinstance(deps, list) or any(not isinstance(x, str) or not x.strip() for x in deps):
            errors.append(f"dependency_list_invalid:{node_id}")
            dependencies[node_id] = []
        else:
            if len(set(deps)) != len(deps):
                errors.append(f"dependency_duplicate:{node_id}")
            dependencies[node_id] = deps
    for node, deps in dependencies.items():
        for dep in deps:
            if dep not in dependencies:
                errors.append(f"dependency_missing:{node}:{dep}")
            if dep == node:
                errors.append(f"dependency_self_reference:{node}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            errors.append(f"dependency_cycle:{node}")
            return
        if node in visited:
            return
        visiting.add(node)
        for dep in dependencies.get(node, []):
            if dep in dependencies:
                visit(dep)
        visiting.remove(node)
        visited.add(node)

    for node in dependencies:
        visit(node)
    return {"stage": 402, "pass": not errors, "errors": errors,
            "node_count": len(dependencies)}


def check_policy_evidence_bindings(bindings: Sequence[Mapping[str, Any]], *,
                                   required_policy_ids: Sequence[str]) -> dict[str, Any]:
    """Stage 403: require explicit unique evidence bindings for every required policy."""
    errors: list[str] = []
    required = list(required_policy_ids)
    if not required or any(not isinstance(x, str) or not x.strip() for x in required):
        errors.append("required_policy_ids_invalid")
    if len(set(required)) != len(required):
        errors.append("required_policy_ids_duplicate")
    seen: set[str] = set()
    for i, item in enumerate(bindings):
        pid, evidence = item.get("policy_id"), item.get("evidence_ids")
        if not isinstance(pid, str) or not pid.strip():
            errors.append(f"binding_policy_id_invalid:{i}")
            continue
        if pid in seen:
            errors.append(f"binding_policy_duplicate:{pid}")
        seen.add(pid)
        if not isinstance(evidence, list) or not evidence or any(not isinstance(x, str) or not x.strip() for x in evidence):
            errors.append(f"binding_evidence_invalid:{pid}")
        elif len(set(evidence)) != len(evidence):
            errors.append(f"binding_evidence_duplicate:{pid}")
    errors.extend(f"policy_binding_missing:{x}" for x in sorted(set(required) - seen))
    errors.extend(f"policy_binding_unexpected:{x}" for x in sorted(seen - set(required)))
    return {"stage": 403, "pass": not errors, "errors": errors,
            "required_policy_count": len(required), "bound_policy_count": len(seen)}


def check_change_control_events(events: Sequence[Mapping[str, Any]], *,
                                evaluation_time: int) -> dict[str, Any]:
    """Stage 404: fail closed on revoked, expired, malformed, or future-dated policy events."""
    errors: list[str] = []
    seen: set[str] = set()
    if isinstance(evaluation_time, bool) or not isinstance(evaluation_time, int) or evaluation_time < 0:
        errors.append("evaluation_time_invalid")
    if not events:
        errors.append("change_control_events_empty")
    for i, event in enumerate(events):
        event_id, state = event.get("event_id"), event.get("state")
        expires, updated = event.get("expires_at"), event.get("updated_at")
        if not isinstance(event_id, str) or not event_id.strip():
            errors.append(f"event_id_invalid:{i}")
        elif event_id in seen:
            errors.append(f"event_id_duplicate:{event_id}")
        else:
            seen.add(event_id)
        if state not in ("active", "revoked"):
            errors.append(f"event_state_invalid:{event_id if isinstance(event_id, str) else i}")
        elif state == "revoked":
            errors.append(f"event_revoked:{event_id}")
        for field, value in (("expires_at", expires), ("updated_at", updated)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                errors.append(f"{field}_invalid:{event_id if isinstance(event_id, str) else i}")
        if isinstance(expires, int) and not isinstance(expires, bool) and isinstance(evaluation_time, int) and not isinstance(evaluation_time, bool):
            if expires <= evaluation_time:
                errors.append(f"event_expired:{event_id}")
        if isinstance(updated, int) and not isinstance(updated, bool) and isinstance(evaluation_time, int) and not isinstance(evaluation_time, bool):
            if updated > evaluation_time:
                errors.append(f"event_updated_in_future:{event_id}")
    return {"stage": 404, "pass": not errors, "errors": errors,
            "event_count": len(seen)}


def evaluate_stages_401_405(*, policies: Sequence[Mapping[str, Any]],
                            dependency_nodes: Sequence[Mapping[str, Any]],
                            policy_bindings: Sequence[Mapping[str, Any]],
                            required_policy_ids: Sequence[str],
                            change_control_events: Sequence[Mapping[str, Any]],
                            evaluation_time: int) -> dict[str, Any]:
    """Stage 405: aggregate policy governance; proposal-only, never execution-authorizing."""
    checks = [
        check_policy_registry(policies),
        check_gate_dependency_graph(dependency_nodes),
        check_policy_evidence_bindings(policy_bindings, required_policy_ids=required_policy_ids),
        check_change_control_events(change_control_events, evaluation_time=evaluation_time),
    ]
    errors: list[str] = []
    policy_ids = {p.get("policy_id") for p in policies if isinstance(p.get("policy_id"), str)}
    if set(required_policy_ids) - policy_ids:
        errors.extend(f"required_policy_not_registered:{x}" for x in sorted(set(required_policy_ids) - policy_ids))
    all_pass = all(c["pass"] for c in checks) and not errors
    payload = {"checks": checks, "errors": errors, "all_pass": all_pass,
               "proposal_only": True, "execution_authorized": False,
               "promotion_authorized": False}
    return {"stage": 405, "status": "PASS" if all_pass else "BLOCKED",
            "checks": checks, "errors": errors, "seal": _seal(payload),
            "proposal_only": True, "execution_authorized": False,
            "promotion_authorized": False}
