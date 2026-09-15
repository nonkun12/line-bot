import pytest

from core.structured_output import parse_json_object, parse_with_retries, require_fields


def test_parse_json_object_accepts_raw_and_fenced_json():
    assert parse_json_object('{"file":"app.py"}') == {"file": "app.py"}
    assert parse_json_object('```json\n{"file":"app.py"}\n```') == {"file": "app.py"}


def test_parse_json_object_extracts_embedded_object():
    assert parse_json_object('Here is the plan: {"file":"app.py"} done.') == {"file": "app.py"}


def test_parse_json_object_rejects_empty_output():
    with pytest.raises(ValueError, match="empty model output"):
        parse_json_object("  ")


def test_parse_with_retries_uses_bounded_attempts_and_validator():
    result = parse_with_retries(
        ["not json", '{"file":"app.py"}', '{"file":"other.py"}'],
        validator=lambda value: require_fields(value, {"file"}),
        max_attempts=2,
    )
    assert result.ok is True
    assert result.value == {"file": "app.py"}
    assert len(result.attempts) == 2
    assert result.attempts[0].success is False
    assert result.attempts[1].success is True


def test_parse_with_retries_fails_closed_after_limit():
    result = parse_with_retries(["not json", "still not json", '{"ok":true}'], max_attempts=2)
    assert result.ok is False
    assert result.value is None
    assert len(result.attempts) == 2


def test_require_fields_does_not_coerce_missing_values():
    with pytest.raises(ValueError, match="missing required fields: file"):
        require_fields({"other": "value"}, {"file"})
