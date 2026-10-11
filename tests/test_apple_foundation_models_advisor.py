"""Tests for the optional Apple Foundation Models advisor; no Apple hardware needed."""
import json
import subprocess
from unittest.mock import patch

import pytest

from scripts.apple_foundation_models_advisor import advise


@patch("scripts.apple_foundation_models_advisor.shutil.which", return_value="/usr/bin/fm")
@patch("scripts.apple_foundation_models_advisor.subprocess.run")
def test_sends_only_sanitized_metadata_and_returns_advice(mock_run, _which):
    mock_run.return_value = subprocess.CompletedProcess(
        args=["fm"], returncode=0, stdout=json.dumps({"advice": "Check the timeout boundary."}), stderr=""
    )
    result = advise("task-1", "timeout", ["tests/test_loop.py::test_timeout"])
    assert result.available is True
    assert result.advice == "Check the timeout boundary."
    prompt = mock_run.call_args.args[0][2]
    assert "timeout" in prompt
    assert mock_run.call_args.kwargs["timeout"] == 20
    assert "OPENAI_API_KEY" not in mock_run.call_args.kwargs["env"]


@patch("scripts.apple_foundation_models_advisor.shutil.which", return_value=None)
def test_missing_cli_fails_closed(_which):
    result = advise("task-1", "timeout")
    assert result.available is False
    assert result.reason == "fm_cli_unavailable"


@patch("scripts.apple_foundation_models_advisor.shutil.which", return_value="/usr/bin/fm")
@patch("scripts.apple_foundation_models_advisor.subprocess.run")
def test_invalid_model_output_is_not_advice(mock_run, _which):
    mock_run.return_value = subprocess.CompletedProcess(args=["fm"], returncode=0, stdout="PASS", stderr="")
    result = advise("task-1", "timeout")
    assert result.available is False
    assert result.reason == "fm_output_not_json"


@patch("scripts.apple_foundation_models_advisor.shutil.which", return_value="/usr/bin/fm")
@patch("scripts.apple_foundation_models_advisor.subprocess.run", side_effect=subprocess.TimeoutExpired("fm", 20))
def test_timeout_fails_closed(_run, _which):
    result = advise("task-1", "timeout")
    assert result.available is False
    assert result.reason == "fm_execution_failed"


def test_rejects_invalid_task_id():
    with pytest.raises(ValueError):
        advise("../unsafe", "timeout")
