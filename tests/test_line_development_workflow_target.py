from line_development import _WORKFLOW_FILE


def test_line_development_dispatches_to_active_workflow():
    assert _WORKFLOW_FILE == "line-development.yml"
