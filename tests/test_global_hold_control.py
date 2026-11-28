from scripts.global_hold_control import (
    CONTROL_ISSUE_NUMBER,
    CONTROL_MARKER,
    CONTROL_TITLE,
    evaluate_global_hold_issue,
)


def issue_payload(**overrides):
    payload = {
        "number": CONTROL_ISSUE_NUMBER,
        "title": CONTROL_TITLE,
        "state": "open",
        "user": {"login": "nonkun12"},
        "body": f"{CONTROL_MARKER}\ncontrol record",
        "pull_request": None,
        "closed_by": None,
        "closed_at": None,
        "state_reason": None,
    }
    # GitHub issue payloads do not include pull_request for ordinary issues.
    payload.pop("pull_request")
    payload.update(overrides)
    return payload


def test_open_control_issue_is_hold():
    assert evaluate_global_hold_issue(issue_payload()) == {
        "dispatch": "false",
        "decision": "SKIPPED_GLOBAL_HOLD_ACTIVE",
        "state": "HOLD",
    }


def test_only_owner_completed_close_clears_global_hold():
    payload = issue_payload(
        state="closed",
        closed_by={"login": "nonkun12"},
        closed_at="2026-11-28T12:00:00Z",
        state_reason="completed",
    )
    assert evaluate_global_hold_issue(payload) == {
        "dispatch": "true",
        "decision": "GLOBAL_HOLD_CLEAR",
        "state": "CLEAR",
    }


def test_non_owner_close_remains_blocked():
    payload = issue_payload(
        state="closed",
        closed_by={"login": "automation-bot"},
        closed_at="2026-11-28T12:00:00Z",
        state_reason="completed",
    )
    assert evaluate_global_hold_issue(payload)["dispatch"] == "false"


def test_closed_without_completed_reason_remains_blocked():
    payload = issue_payload(
        state="closed",
        closed_by={"login": "nonkun12"},
        closed_at="2026-11-28T12:00:00Z",
        state_reason="not_planned",
    )
    assert evaluate_global_hold_issue(payload)["state"] == "UNKNOWN_BLOCKED"


def test_reopened_issue_is_hold_even_if_old_close_metadata_exists():
    payload = issue_payload(
        state="open",
        closed_by={"login": "nonkun12"},
        closed_at="2026-11-28T12:00:00Z",
        state_reason="completed",
    )
    assert evaluate_global_hold_issue(payload)["state"] == "HOLD"


def test_wrong_issue_identity_or_missing_marker_fails_closed():
    for payload in (
        issue_payload(number=999),
        issue_payload(title="ordinary issue"),
        issue_payload(body="no marker"),
        issue_payload(user={"login": "someone-else"}),
        issue_payload(body=f"{CONTROL_MARKER}\n{CONTROL_MARKER}"),
    ):
        assert evaluate_global_hold_issue(payload)["dispatch"] == "false"


def test_pull_request_payload_cannot_be_used_as_control_issue():
    payload = issue_payload()
    payload["pull_request"] = {"url": "https://example.invalid"}
    assert evaluate_global_hold_issue(payload)["dispatch"] == "false"


def test_malformed_payload_and_wrong_configured_number_fail_closed():
    assert evaluate_global_hold_issue(None)["dispatch"] == "false"
    assert evaluate_global_hold_issue(issue_payload(), issue_number=999)["dispatch"] == "false"


def test_missing_close_actor_or_timestamp_fails_closed():
    payload = issue_payload(state="closed", state_reason="completed")
    assert evaluate_global_hold_issue(payload)["dispatch"] == "false"
    payload["closed_by"] = {"login": "nonkun12"}
    assert evaluate_global_hold_issue(payload)["dispatch"] == "false"
