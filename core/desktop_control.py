"""Safe, provider-injected planning contract for local CAD and spreadsheet control.

This module converts a local model's structured proposal into a bounded plan.
It deliberately does not operate the desktop, execute macros, run shell commands,
or write files. A separately reviewed local desktop runner is required.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable


MAX_REQUEST_CHARS = 4000
MAX_PLAN_BYTES = 32768
MAX_ACTIONS = 20
MAX_TEXT = 1000

# The allowlist is intentionally narrow. Arbitrary code, macros, shell commands,
# browser navigation, file deletion, and network transfer are never valid actions.
APP_OPERATIONS: dict[str, frozenset[str]] = {
    "freecad": frozenset({
        "open_document", "inspect_model", "create_sketch", "add_hole",
        "extrude", "export_step", "save_as",
    }),
    "excel": frozenset({
        "open_workbook", "inspect_sheet", "write_cells", "create_formula",
        "create_chart", "save_as",
    }),
}
READ_ONLY = frozenset({
    "open_document", "inspect_model", "open_workbook", "inspect_sheet",
})
HIGH_RISK = frozenset({"save_as", "export_step"})
FORMULA_DANGEROUS = re.compile(
    r"(WEBSERVICE|HYPERLINK|DDE|REGISTER|CALL|RTD)\s*\(|\[[^]]+\]",
    re.IGNORECASE,
)


class DesktopPlanError(ValueError):
    """A request or model-proposed plan violates the desktop safety contract."""


@dataclass(frozen=True)
class DesktopPlan:
    schema_version: int
    request: str
    app: str
    goal: str
    actions: tuple[dict[str, Any], ...]
    plan_sha256: str
    requires_human_confirmation: bool
    execution_authorized: bool = False
    execution_performed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request": self.request,
            "app": self.app,
            "goal": self.goal,
            "actions": [dict(action) for action in self.actions],
            "plan_sha256": self.plan_sha256,
            "requires_human_confirmation": self.requires_human_confirmation,
            "execution_authorized": self.execution_authorized,
            "execution_performed": self.execution_performed,
        }


def _bounded_text(value: Any, field: str, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise DesktopPlanError(f"invalid_{field}")
    return value.strip()


def _validate_params(app: str, operation: str, params: Any) -> dict[str, Any]:
    if not isinstance(params, dict) or len(params) > 12:
        raise DesktopPlanError("invalid_action_params")

    # Reject code-like payloads even if a future model prompt accidentally asks
    # for them. Only structured values are accepted by the runner contract.
    forbidden_keys = {"command", "shell", "script", "macro", "vba", "python", "javascript", "url"}
    if any(str(key).casefold() in forbidden_keys for key in params):
        raise DesktopPlanError("executable_or_network_payload_forbidden")

    if operation in {"open_document", "open_workbook", "save_as", "export_step"}:
        path = _bounded_text(params.get("path"), "path", 2048)
        if path.startswith(("http://", "https://", "smb://", "\\\\")):
            raise DesktopPlanError("remote_path_forbidden")
        return {"path": path}

    if operation == "inspect_model":
        if params and set(params) != {"object_name"}:
            raise DesktopPlanError("unexpected_inspect_model_params")
        return {"object_name": _bounded_text(params["object_name"], "object_name", 160)} if params else {}

    if operation == "inspect_sheet":
        if params and set(params) != {"sheet_name"}:
            raise DesktopPlanError("unexpected_inspect_sheet_params")
        return {"sheet_name": _bounded_text(params["sheet_name"], "sheet_name", 128)} if params else {}

    if operation == "create_sketch":
        if set(params) != {"plane", "geometry"}:
            raise DesktopPlanError("invalid_create_sketch_params")
        plane = _bounded_text(params["plane"], "plane", 32).upper()
        if plane not in {"XY", "XZ", "YZ"}:
            raise DesktopPlanError("unsupported_sketch_plane")
        geometry = params["geometry"]
        if not isinstance(geometry, list) or not 1 <= len(geometry) <= 100:
            raise DesktopPlanError("invalid_sketch_geometry")
        # Geometry remains structured data, never executable FreeCAD Python.
        for item in geometry:
            if not isinstance(item, dict) or item.get("type") not in {"line", "circle", "rectangle"}:
                raise DesktopPlanError("unsupported_sketch_geometry")
        return {"plane": plane, "geometry": geometry}

    if operation == "add_hole":
        if set(params) != {"diameter_mm", "positions"}:
            raise DesktopPlanError("invalid_add_hole_params")
        diameter = params["diameter_mm"]
        positions = params["positions"]
        if isinstance(diameter, bool) or not isinstance(diameter, (int, float)) or not 0 < diameter <= 10000:
            raise DesktopPlanError("invalid_hole_diameter")
        if not isinstance(positions, list) or not 1 <= len(positions) <= 100:
            raise DesktopPlanError("invalid_hole_positions")
        for point in positions:
            if not isinstance(point, dict) or set(point) != {"x_mm", "y_mm", "z_mm"}:
                raise DesktopPlanError("invalid_hole_position")
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or abs(v) > 1_000_000 for v in point.values()):
                raise DesktopPlanError("invalid_hole_coordinate")
        return {"diameter_mm": float(diameter), "positions": positions}

    if operation == "extrude":
        if set(params) != {"depth_mm"}:
            raise DesktopPlanError("invalid_extrude_params")
        depth = params["depth_mm"]
        if isinstance(depth, bool) or not isinstance(depth, (int, float)) or not 0 < depth <= 1_000_000:
            raise DesktopPlanError("invalid_extrude_depth")
        return {"depth_mm": float(depth)}

    if operation == "write_cells":
        if set(params) != {"sheet_name", "range", "values"}:
            raise DesktopPlanError("invalid_write_cells_params")
        sheet = _bounded_text(params["sheet_name"], "sheet_name", 128)
        cell_range = _bounded_text(params["range"], "cell_range", 64)
        values = params["values"]
        if not isinstance(values, list) or not 1 <= len(values) <= 500:
            raise DesktopPlanError("invalid_cell_values")
        if any(not isinstance(row, list) or len(row) > 100 for row in values):
            raise DesktopPlanError("invalid_cell_matrix")
        for row in values:
            for value in row:
                if not isinstance(value, (str, int, float, bool, type(None))) or (isinstance(value, str) and len(value) > 4000):
                    raise DesktopPlanError("invalid_cell_value")
                if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
                    raise DesktopPlanError("formula_requires_explicit_create_formula")
        return {"sheet_name": sheet, "range": cell_range, "values": values}

    if operation == "create_formula":
        if set(params) != {"sheet_name", "cell", "formula"}:
            raise DesktopPlanError("invalid_create_formula_params")
        formula = _bounded_text(params["formula"], "formula", 1000)
        if not formula.startswith("=") or FORMULA_DANGEROUS.search(formula):
            raise DesktopPlanError("unsafe_excel_formula")
        return {
            "sheet_name": _bounded_text(params["sheet_name"], "sheet_name", 128),
            "cell": _bounded_text(params["cell"], "cell", 16),
            "formula": formula,
        }

    if operation == "create_chart":
        if set(params) != {"sheet_name", "data_range", "chart_type"}:
            raise DesktopPlanError("invalid_create_chart_params")
        chart_type = _bounded_text(params["chart_type"], "chart_type", 24).casefold()
        if chart_type not in {"column", "bar", "line", "pie", "scatter"}:
            raise DesktopPlanError("unsupported_chart_type")
        return {
            "sheet_name": _bounded_text(params["sheet_name"], "sheet_name", 128),
            "data_range": _bounded_text(params["data_range"], "data_range", 64),
            "chart_type": chart_type,
        }

    raise DesktopPlanError("unsupported_operation")


def validate_plan(document: Any, *, original_request: str) -> DesktopPlan:
    """Validate untrusted model JSON and return a deterministic plan preview."""
    request = _bounded_text(original_request, "request", MAX_REQUEST_CHARS)
    if not isinstance(document, dict) or set(document) != {"schema_version", "app", "goal", "actions"}:
        raise DesktopPlanError("invalid_plan_shape")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise DesktopPlanError("unsupported_schema_version")
    app = _bounded_text(document["app"], "app", 32).casefold()
    if app not in APP_OPERATIONS:
        raise DesktopPlanError("unsupported_app")
    goal = _bounded_text(document["goal"], "goal", 500)
    actions_doc = document["actions"]
    if not isinstance(actions_doc, list) or not 1 <= len(actions_doc) <= MAX_ACTIONS:
        raise DesktopPlanError("invalid_action_count")

    actions: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in actions_doc:
        if not isinstance(item, dict) or set(item) != {"id", "operation", "params"}:
            raise DesktopPlanError("invalid_action_shape")
        action_id = _bounded_text(item["id"], "action_id", 40)
        if action_id in seen_ids:
            raise DesktopPlanError("duplicate_action_id")
        seen_ids.add(action_id)
        operation = _bounded_text(item["operation"], "operation", 40)
        if operation not in APP_OPERATIONS[app]:
            raise DesktopPlanError("operation_not_allowed_for_app")
        params = _validate_params(app, operation, item["params"])
        risk = "read_only" if operation in READ_ONLY else "high" if operation in HIGH_RISK else "modifying"
        actions.append({
            "id": action_id,
            "operation": operation,
            "params": params,
            "risk": risk,
            "requires_human_confirmation": risk != "read_only",
        })

    canonical = json.dumps(
        {"schema_version": 1, "request": request, "app": app, "goal": goal, "actions": actions},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    if len(canonical) > MAX_PLAN_BYTES:
        raise DesktopPlanError("plan_too_large")
    digest = hashlib.sha256(canonical).hexdigest()
    return DesktopPlan(
        schema_version=1,
        request=request,
        app=app,
        goal=goal,
        actions=tuple(actions),
        plan_sha256=digest,
        requires_human_confirmation=any(a["requires_human_confirmation"] for a in actions),
    )


def plan_natural_language_request(
    request: str,
    local_model: Callable[[str], str],
) -> DesktopPlan:
    """Ask an injected local-only model for JSON, then validate every field."""
    request = _bounded_text(request, "request", MAX_REQUEST_CHARS)
    prompt = (
        "Convert the user's desktop task into one JSON object only. "
        "No markdown, code, scripts, macros, shell commands, or URLs. "
        "Allowed apps: freecad, excel. Allowed operations and exact parameter "
        "schemas are enforced by the host; choose only a plausible operation. "
        "If details are missing, return a single read-only inspect action rather "
        "than invent dimensions, cell ranges, filenames, or values. "
        "Schema: {schema_version:1, app:string, goal:string, actions:[{id:string, "
        "operation:string, params:object}]}. User request: " + request
    )
    raw = local_model(prompt)
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_PLAN_BYTES:
        raise DesktopPlanError("model_response_invalid_or_oversized")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DesktopPlanError("model_response_not_json") from exc
    return validate_plan(document, original_request=request)


class DesktopExecutionDisabled(RuntimeError):
    """Raised because the live desktop runner has not been installed and approved."""


class DesktopRunner:
    """Fail-closed placeholder for the future Computer Use backend."""

    def execute(self, plan: DesktopPlan) -> None:
        raise DesktopExecutionDisabled(
            "live_desktop_runner_not_installed; plan preview only"
        )


__all__ = [
    "DesktopExecutionDisabled",
    "DesktopPlan",
    "DesktopPlanError",
    "DesktopRunner",
    "plan_natural_language_request",
    "validate_plan",
]
