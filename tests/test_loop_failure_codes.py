from core.loop_failure_codes import extract_safe_failure_code, is_safe_failure_code


def test_extracts_only_allowlisted_failure_code_from_runtime_detail():
    assert extract_safe_failure_code(
        "implementation plan rejected: existing_test_modified_repair_failed"
    ) == "existing_test_modified_repair_failed"


def test_untrusted_or_unknown_failure_text_is_not_preserved():
    assert extract_safe_failure_code("token=secret-value unexpected traceback") is None
    assert extract_safe_failure_code("unknown_failure_code") is None
    assert not is_safe_failure_code("existing_test_modified_repair_failed; raw detail")


def test_extracts_invalid_change_count_as_a_safe_failure_code():
    assert extract_safe_failure_code("apply failed: invalid_change_count") == "invalid_change_count"
    assert is_safe_failure_code("invalid_change_count")
