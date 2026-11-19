from scripts.app_development_worker import parse_json


def test_parse_raw_json_object():
    assert parse_json('{"files": [], "summary": "ok"}') == {"files": [], "summary": "ok"}


def test_parse_fenced_json():
    assert parse_json('```json\n{"files": [], "summary": "ok"}\n```')["summary"] == "ok"


def test_parse_tagless_fence():
    assert parse_json('```\n{"files": [], "summary": "ok"}\n```')["summary"] == "ok"


def test_parse_json_with_leading_prose():
    result = parse_json('Here is the plan:\n{"files": [], "summary": "ok"}')
    assert result["summary"] == "ok"


def test_parse_json_with_trailing_prose():
    result = parse_json('{"files": [], "summary": "ok"}\nDone.')
    assert result["summary"] == "ok"


def test_parse_empty_response_is_explicit():
    try:
        parse_json("")
    except ValueError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_parse_whitespace_response_is_explicit():
    try:
        parse_json("   \n\t")
    except ValueError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_parse_no_json_object_is_explicit():
    try:
        parse_json("plain text without json")
    except ValueError as exc:
        assert "JSON object" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_parse_non_object_json_is_rejected():
    try:
        parse_json('[{"files": []}]')
    except ValueError as exc:
        assert "JSON object" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_parse_json_object_after_other_braces():
    result = parse_json('AI note {not valid json} then {"files": [], "summary": "ok"}')
    assert result["summary"] == "ok"
