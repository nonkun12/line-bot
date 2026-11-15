"""Fail-closed natural-language plan contract for local CAD and spreadsheets.

Phase 0 validates model proposals only. It never operates the desktop or writes files.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Callable

MAX_REQUEST_CHARS = 4000
MAX_PLAN_BYTES = 32768
MAX_ACTIONS = 20
MAX_TEXT = 1000

CAD_OPERATIONS = frozenset({
    "open_document", "inspect_model", "create_sketch", "add_hole",
    "extrude", "export_step", "save_as",
})
SHEET_OPERATIONS = frozenset({
    "open_workbook", "inspect_sheet", "write_cells", "create_formula",
    "create_chart", "save_as",
})
APP_OPERATIONS = {
    "cad": CAD_OPERATIONS,
    "excel": SHEET_OPERATIONS,
    "libreoffice_calc": SHEET_OPERATIONS,
}
READ_ONLY = frozenset({
    "open_document", "inspect_model", "open_workbook", "inspect_sheet",
})
HIGH_RISK = frozenset({"save_as", "export_step"})
FORMULA_DANGEROUS = re.compile(
    r"(WEBSERVICE|HYPERLINK|DDE|REGISTER|CALL|RTD)\s*\(|\[[^]]+\]",
    re.IGNORECASE,
)
CELL_RANGE = re.compile(
    r"^\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6}(?::\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6})?$",
    re.IGNORECASE,
)
SINGLE_CELL = re.compile(r"^\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6}$", re.IGNORECASE)


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


def _text(value: Any, field: str, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise DesktopPlanError(f"invalid_{field}")
    return value.strip()


def _number(value: Any, field: str, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DesktopPlanError(f"invalid_{field}")
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise DesktopPlanError(f"invalid_{field}")
    return float(value)


def _local_path(params: dict[str, Any]) -> dict[str, str]:
    path = _text(params.get("path"), "path", 2048)
    if path.startswith(("http://", "https://", "smb://", "\\\\\\")):
        raise DesktopPlanError("remote_path_forbidden")
    return {"path": path}


def _validate_params(app: str, operation: str, params: Any) -> dict[str, Any]:
    if not isinstance(params, dict) or len(params) > 12:
        raise DesktopPlanError("invalid_action_params")
    forbidden = {"command", "shell", "script", "macro", "vba", "python", "javascript", "url"}
    if any(str(key).casefold() in forbidden for key in params):
        raise DesktopPlanError("executable_or_network_payload_forbidden")

    if operation in {"open_document", "open_workbook", "save_as", "export_step"}:
        return _local_path(params)

    if operation == "inspect_model":
        if params and set(params) != {"object_name"}:
            raise DesktopPlanError("unexpected_inspect_model_params")
        return {"object_name": _text(params["object_name"], "object_name", 160)} if params else {}

    if operation == "inspect_sheet":
        if params and set(params) != {"sheet_name"}:
            raise DesktopPlanError("unexpected_inspect_sheet_params")
        return {"sheet_name": _text(params["sheet_name"], "sheet_name", 128)} if params else {}

    if operation == "create_sketch":
        if set(params) != {"plane", "geometry"}:
            raise DesktopPlanError("invalid_create_sketch_params")
        plane = _text(params["plane"], "plane", 8).upper()
        if plane not in {"XY", "XZ", "YZ"}:
            raise DesktopPlanError("unsupported_sketch_plane")
        geometry = params["geometry"]
        if not isinstance(geometry, list) or not 1 <= len(geometry) <= 100:
            raise DesktopPlanError("invalid_sketch_geometry")
        fields = {
            "line": {"type", "x1_mm", "y1_mm", "x2_mm", "y2_mm"},
            "circle": {"type", "x_mm", "y_mm", "radius_mm"},
            "rectangle": {"type", "x_mm", "y_mm", "width_mm", "height_mm"},
        }
        normalized = []
        for item in geometry:
            if not isinstance(item, dict) or item.get("type") not in fields:
                raise DesktopPlanError("unsupported_sketch_geometry")
            kind = item["type"]
            if set(item) != fields[kind]:
                raise DesktopPlanError("invalid_sketch_geometry_fields")
            shape = {"type": kind}
            for key, value in item.items():
                if key == "type":
                    continue
                minimum = 0.000001 if key in {"radius_mm", "width_mm", "height_mm"} else -1_000_000
                shape[key] = _number(value, key, minimum=minimum, maximum=1_000_000)
            normalized.append(shape)
        return {"plane": plane, "geometry": normalized}

    if operation == "add_hole":
        if set(params) != {"diameter_mm", "positions"}:
            raise DesktopPlanError("invalid_add_hole_params")
        diameter = _number(params["diameter_mm"], "hole_diameter", minimum=0.000001, maximum=10000)
        positions = params["positions"]
        if not isinstance(positions, list) or not 1 <= len(positions) <= 100:
            raise DesktopPlanError("invalid_hole_positions")
        normalized_positions = []
        for point in positions:
            if not isinstance(point, dict) or set(point) != {"x_mm", "y_mm", "z_mm"}:
                raise DesktopPlanError("invalid_hole_position")
            normalized_positions.append({
                key: _number(value, "hole_coordinate", minimum=-1_000_000, maximum=1_000_000)
                for key, value in point.items()
            })
        return {"diameter_mm": diameter, "positions": normalized_positions}

    if operation == "extrude":
        if set(params) != {"depth_mm"}:
            raise DesktopPlanError("invalid_extrude_params")
        return {"depth_mm": _number(params["depth_mm"], "extrude_depth", minimum=0.000001, maximum=1_000_000)}

    if operation == "write_cells":
        if set(params) != {"sheet_name", "range", "values"}:
            raise DesktopPlanError("invalid_write_cells_params")
        cell_range = _text(params["range"], "cell_range", 64)
        if not CELL_RANGE.fullmatch(cell_range):
            raise DesktopPlanError("invalid_cell_range")
        values = params["values"]
        if not isinstance(values, list) or not 1 <= len(values) <= 500:
            raise DesktopPlanError("invalid_cell_values")
        if any(not isinstance(row, list) or not 1 <= len(row) <= 100 for row in values):
            raise DesktopPlanError("invalid_cell_matrix")
        for row in values:
            for value in row:
                if not isinstance(value, (str, int, float, bool, type(None))):
                    raise DesktopPlanError("invalid_cell_value")
                if isinstance(value, str) and (len(value) > 4000 or value.startswith(("=", "+", "-", "@"))):
                    raise DesktopPlanError("formula_requires_explicit_create_formula")
                if isinstance(value, float) and not math.isfinite(value):
                    raise DesktopPlanError("invalid_cell_value")
        return {
            "sheet_name": _text(params["sheet_name"], "sheet_name", 128),
            "range": cell_range,
            "values": values,
        }

    if operation == "create_formula":
        if set(params) != {"sheet_name", "cell", "formula"}:
            raise DesktopPlanError("invalid_create_formula_params")
        cell = _text(params["cell"], "cell", 16)
        formula = _text(params["formula"], "formula", 1000)
        if not SINGLE_CELL.fullmatch(cell):
            raise DesktopPlanError("invalid_formula_cell")
        if not formula.startswith("=") or FORMULA_DANGEROUS.search(formula) or "|" in formula or "!" in formula:
            raise DesktopPlanError("unsafe_excel_formula")
        return {
            "sheet_name": _text(params["sheet_name"], "sheet_name", 128),
            "cell": cell,
            "formula": formula,
        }

    if operation == "create_chart":
        if set(params) != {"sheet_name", "data_range", "chart_type"}:
            raise DesktopPlanError("invalid_create_chart_params")
        data_range = _text(params["data_range"], "data_range", 64)
        if not CELL_RANGE.fullmatch(data_range):
            raise DesktopPlanError("invalid_chart_data_range")
        chart_type = _text(params["chart_type"], "chart_type", 24).casefold()
        if chart_type not in {"column", "bar", "line", "pie", "scatter"}:
            raise DesktopPlanError("unsupported_chart_type")
        return {
            "sheet_name": _text(params["sheet_name"], "sheet_name", 128),
            "data_range": data_range,
            "chart_type": chart_type,
        }

    raise DesktopPlanError("unsupported_operation")


def validate_plan(document: Any, *, original_request: str) -> DesktopPlan:
    """Validate untrusted model JSON and return a deterministic plan preview."""
    request = _text(original_request, "request", MAX_REQUEST_CHARS)
    if not isinstance(document, dict) or set(document) != {"schema_version", "app", "goal", "actions"}:
        raise DesktopPlanError("invalid_plan_shape")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise DesktopPlanError("unsupported_schema_version")
    app = _text(document["app"], "app", 32).casefold()
    if app not in APP_OPERATIONS:
        raise DesktopPlanError("unsupported_app")
    goal = _text(document["goal"], "goal", 500)
    proposed = document["actions"]
    if not isinstance(proposed, list) or not 1 <= len(proposed) <= MAX_ACTIONS:
        raise DesktopPlanError("invalid_action_count")

    actions = []
    seen = set()
    for item in proposed:
        if not isinstance(item, dict) or set(item) != {"id", "operation", "params"}:
            raise DesktopPlanError("invalid_action_shape")
        action_id = _text(item["id"], "action_id", 40)
        if action_id in seen:
            raise DesktopPlanError("duplicate_action_id")
        seen.add(action_id)
        operation = _text(item["operation"], "operation", 40)
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
    return DesktopPlan(
        schema_version=1,
        request=request,
        app=app,
        goal=goal,
        actions=tuple(actions),
        plan_sha256=hashlib.sha256(canonical).hexdigest(),
        requires_human_confirmation=any(a["requires_human_confirmation"] for a in actions),
    )


def plan_natural_language_request(request: str, local_model: Callable[[str], str]) -> DesktopPlan:
    """Ask an injected local-only model for JSON, then validate every field."""
    request = _text(request, "request", MAX_REQUEST_CHARS)
    prompt = (
        "Convert the user's desktop task into one JSON object only. No markdown, code, "
        "scripts, macros, shell commands, or URLs. Allowed apps: cad, excel, "
        "libreoffice_calc. Use only allowlisted operations. If dimensions, coordinates, "
        "cell ranges, or paths are missing, request inspection instead of inventing them. "
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
    """Raised because the live local desktop runner is not yet enabled."""


class DesktopRunner:
    """Phase 0 placeholder. A real, separately reviewed local runner is required."""

    def execute(self, plan: DesktopPlan) -> None:
        raise DesktopExecutionDisabled("local_computer_use_runner_not_installed; plan preview only")


__all__ = [
    "DesktopExecutionDisabled", "DesktopPlan", "DesktopPlanError",
    "DesktopRunner", "plan_natural_language_request", "validate_plan",
]
