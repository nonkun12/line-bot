from __future__ import annotations

import json

import pytest

from core.desktop_control import (
    DesktopExecutionDisabled,
    DesktopPlanError,
    DesktopRunner,
    plan_natural_language_request,
    validate_plan,
)


def _plan(app="excel", operation="inspect_sheet", params=None):
    return {
        "schema_version": 1,
        "app": app,
        "goal": "Inspect the document",
        "actions": [{
            "id": "a1",
            "operation": operation,
            "params": {} if params is None else params,
        }],
    }


@pytest.mark.parametrize("app", ["excel", "libreoffice_calc"])
def test_spreadsheet_read_only_plan_is_preview_only(app):
    plan = validate_plan(_plan(app), original_request="売上シートを確認して")
    assert plan.app == app
    assert plan.requires_human_confirmation is False
    assert plan.execution_authorized is False
    assert plan.execution_performed is False
    assert len(plan.plan_sha256) == 64


def test_cell_write_requires_human_confirmation():
    plan = validate_plan(
        _plan(operation="write_cells", params={
            "sheet_name": "売上",
            "range": "A1:B2",
            "values": [["月", "売上"], ["1月", 100]],
        }),
        original_request="表を入力して",
    )
    assert plan.requires_human_confirmation is True
    assert plan.actions[0]["risk"] == "modifying"


def test_vendor_neutral_cad_hole_plan():
    plan = validate_plan(
        _plan("cad", "add_hole", {
            "diameter_mm": 20,
            "positions": [{"x_mm": 0, "y_mm": 0, "z_mm": 0}],
        }),
        original_request="直径20mmの穴を追加して",
    )
    assert plan.app == "cad"
    assert plan.actions[0]["params"]["diameter_mm"] == 20.0


def test_cad_sketch_geometry_is_fully_validated():
    plan = validate_plan(
        _plan("cad", "create_sketch", {
            "plane": "XY",
            "geometry": [{"type": "circle", "x_mm": 0, "y_mm": 0, "radius_mm": 5}],
        }),
        original_request="円を作図して",
    )
    assert plan.actions[0]["params"]["geometry"][0]["radius_mm"] == 5.0


@pytest.mark.parametrize("app", ["excel", "libreoffice_calc"])
@pytest.mark.parametrize("operation,params", [
    ("write_cells", {
        "sheet_name": "Sheet1", "range": "A1", "values": [["=WEBSERVICE(\"https://bad\")"]],
    }),
    ("create_formula", {
        "sheet_name": "Sheet1", "cell": "A1", "formula": "=HYPERLINK(\"https://bad\",\"click\")",
    }),
    ("write_cells", {
        "sheet_name": "Sheet1", "range": "A1", "values": [["=1+1"]],
    }),
    ("write_cells", {
        "sheet_name": "Sheet1", "range": "A0", "values": [[1]],
    }),
])
def test_unsafe_spreadsheet_values_are_rejected(app, operation, params):
    with pytest.raises(DesktopPlanError):
        validate_plan(_plan(app, operation, params), original_request="実行して")


def test_non_finite_cad_dimensions_are_rejected():
    with pytest.raises(DesktopPlanError):
        validate_plan(
            _plan("cad", "add_hole", {
                "diameter_mm": float("inf"),
                "positions": [{"x_mm": 0, "y_mm": 0, "z_mm": 0}],
            }),
            original_request="穴を追加して",
        )


def test_cross_app_operation_is_rejected():
    with pytest.raises(DesktopPlanError, match="operation_not_allowed_for_app"):
        validate_plan(_plan("excel", "add_hole", {}), original_request="穴を作成")


def test_model_output_is_validated_before_use():
    def model(_prompt):
        return json.dumps(_plan("libreoffice_calc"), ensure_ascii=False)

    plan = plan_natural_language_request("Calcを確認", model)
    assert plan.app == "libreoffice_calc"
    assert plan.execution_authorized is False


def test_model_cannot_return_executable_payload():
    bad = _plan(operation="inspect_sheet", params={"script": "import os"})
    with pytest.raises(DesktopPlanError):
        validate_plan(bad, original_request="Excelを確認")


def test_remote_paths_are_rejected():
    with pytest.raises(DesktopPlanError, match="remote_path_forbidden"):
        validate_plan(
            _plan("cad", "open_document", {"path": "https://example.com/model.step"}),
            original_request="図面を開いて",
        )


def test_live_runner_fails_closed():
    plan = validate_plan(_plan(), original_request="Excelを確認")
    with pytest.raises(DesktopExecutionDisabled):
        DesktopRunner().execute(plan)
