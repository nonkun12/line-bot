"""Proposal-only reproducibility declaration checks for AI Factory stages 416-420."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _seal(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _digest(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256.fullmatch(value))


def check_reproduction_manifest(manifests: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 416: validate complete, uniquely identified reproduction manifests."""
    errors: list[str] = []
    seen: set[str] = set()
    if not manifests:
        errors.append("manifests_empty")
    for i, item in enumerate(manifests):
        manifest_id = item.get("manifest_id")
        if not _nonempty(manifest_id):
            errors.append(f"manifest_id_invalid:{i}")
        elif manifest_id in seen:
            errors.append(f"manifest_id_duplicate:{manifest_id}")
        else:
            seen.add(manifest_id)
        for field in ("schema_version", "code_version", "runtime", "config_digest"):
            if not _nonempty(item.get(field)):
                errors.append(f"manifest_{field}_missing:{manifest_id if _nonempty(manifest_id) else i}")
        if not _digest(item.get("config_digest")):
            errors.append(f"manifest_config_digest_invalid:{manifest_id if _nonempty(manifest_id) else i}")
        inputs = item.get("inputs")
        if not isinstance(inputs, list) or not inputs:
            errors.append(f"manifest_inputs_empty_or_invalid:{manifest_id if _nonempty(manifest_id) else i}")
            continue
        refs: set[str] = set()
        for j, source in enumerate(inputs):
            if not isinstance(source, Mapping):
                errors.append(f"manifest_input_invalid:{i}:{j}")
                continue
            ref, digest = source.get("ref"), source.get("sha256")
            if not _nonempty(ref):
                errors.append(f"manifest_input_ref_invalid:{i}:{j}")
            elif ref in refs:
                errors.append(f"manifest_input_ref_duplicate:{manifest_id}:{ref}")
            else:
                refs.add(ref)
            if not _digest(digest):
                errors.append(f"manifest_input_digest_invalid:{manifest_id}:{j}")
    return {"stage": 416, "pass": not errors, "errors": errors, "manifest_count": len(seen)}


def check_artifact_lineage(links: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 417: validate declared input/output artifact links and digest shapes."""
    errors: list[str] = []
    seen_outputs: set[str] = set()
    if not links:
        errors.append("artifact_links_empty")
    for i, item in enumerate(links):
        run_id, output_ref = item.get("run_id"), item.get("output_ref")
        if not _nonempty(run_id):
            errors.append(f"lineage_run_id_invalid:{i}")
        if not _nonempty(output_ref):
            errors.append(f"lineage_output_ref_invalid:{i}")
        elif output_ref in seen_outputs:
            errors.append(f"lineage_output_duplicate:{output_ref}")
        else:
            seen_outputs.add(output_ref)
        if not _digest(item.get("output_sha256")):
            errors.append(f"lineage_output_digest_invalid:{i}")
        inputs = item.get("input_refs")
        if not isinstance(inputs, list) or not inputs:
            errors.append(f"lineage_inputs_empty_or_invalid:{i}")
        elif any(not _nonempty(ref) for ref in inputs) or len(set(inputs)) != len(inputs):
            errors.append(f"lineage_input_refs_invalid_or_duplicate:{i}")
    return {"stage": 417, "pass": not errors, "errors": errors, "link_count": len(seen_outputs)}


def check_replay_consistency(replays: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 418: require repeated declared runs for a case to report the same output digest."""
    errors: list[str] = []
    grouped: dict[str, set[str]] = {}
    if not replays:
        errors.append("replays_empty")
    for i, item in enumerate(replays):
        case_id, run_id, digest = item.get("case_id"), item.get("run_id"), item.get("output_sha256")
        if not _nonempty(case_id):
            errors.append(f"replay_case_id_invalid:{i}")
        if not _nonempty(run_id):
            errors.append(f"replay_run_id_invalid:{i}")
        if not _digest(digest):
            errors.append(f"replay_output_digest_invalid:{i}")
        if _nonempty(case_id) and _digest(digest):
            grouped.setdefault(case_id, set()).add(digest)
    for case_id, digests in grouped.items():
        if len(digests) != 1:
            errors.append(f"replay_output_mismatch:{case_id}")
    return {"stage": 418, "pass": not errors, "errors": errors, "case_count": len(grouped)}


def check_execution_environment(environments: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 419: require explicit environment declarations for each run."""
    errors: list[str] = []
    seen: set[str] = set()
    if not environments:
        errors.append("environments_empty")
    for i, item in enumerate(environments):
        run_id = item.get("run_id")
        if not _nonempty(run_id):
            errors.append(f"environment_run_id_invalid:{i}")
        elif run_id in seen:
            errors.append(f"environment_run_duplicate:{run_id}")
        else:
            seen.add(run_id)
        for field in ("runtime", "platform", "dependency_lock_digest", "seed_policy"):
            if not _nonempty(item.get(field)):
                errors.append(f"environment_{field}_missing:{run_id if _nonempty(run_id) else i}")
        if not _digest(item.get("dependency_lock_digest")):
            errors.append(f"environment_dependency_digest_invalid:{run_id if _nonempty(run_id) else i}")
    return {"stage": 419, "pass": not errors, "errors": errors, "environment_count": len(seen)}


def evaluate_stages_416_420(*, manifests: Sequence[Mapping[str, Any]],
                            artifact_links: Sequence[Mapping[str, Any]],
                            replays: Sequence[Mapping[str, Any]],
                            environments: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 420: fail-closed declaration gate; it does not execute a replay."""
    checks = [
        check_reproduction_manifest(manifests),
        check_artifact_lineage(artifact_links),
        check_replay_consistency(replays),
        check_execution_environment(environments),
    ]
    errors: list[str] = []
    manifest_ids = {x.get("manifest_id") for x in manifests if _nonempty(x.get("manifest_id"))}
    run_ids = {x.get("run_id") for x in artifact_links if _nonempty(x.get("run_id"))}
    env_run_ids = {x.get("run_id") for x in environments if _nonempty(x.get("run_id"))}
    errors.extend(f"lineage_run_without_environment:{x}" for x in sorted(run_ids - env_run_ids))
    errors.extend(f"environment_without_lineage:{x}" for x in sorted(env_run_ids - run_ids))
    if not manifest_ids:
        errors.append("no_valid_manifest_identity")
    passed = all(check["pass"] for check in checks) and not errors
    payload = {"checks": checks, "errors": errors, "all_pass": passed,
               "proposal_only": True, "execution_authorized": False,
               "promotion_authorized": False}
    return {"stage": 420, "status": "PASS" if passed else "BLOCKED",
            "checks": checks, "errors": errors, "seal": _seal(payload),
            "proposal_only": True, "execution_authorized": False,
            "promotion_authorized": False}
