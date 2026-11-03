import pytest
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


@pytest.mark.parametrize(
    "evidence,expected",
    [
        ("provider response status=429", "provider_rate_limited"),
        ("provider response status=503", "provider_service_unavailable"),
        ("provider response status=408", "provider_service_unavailable"),
        ("APIConnectionError: connection reset", "provider_network_transient"),
        ("APITimeoutError: request timed out", "provider_network_transient"),
        ("provider response status=400", None),
        ("provider response status=401", None),
    ],
)
def test_extract_safe_transient_provider_signals(evidence, expected):
    assert extract_safe_failure_code(evidence) == expected
