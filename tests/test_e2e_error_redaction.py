import e2e_status


def test_safe_error_redacts_string_contents():
    assert e2e_status._safe_error("secret user input: 12345") == "error"


def test_safe_error_keeps_exception_type_without_message():
    assert e2e_status._safe_error(ValueError("secret user input")) == "ValueError"


def test_safe_error_does_not_stringify_exception_message():
    class SecretError(Exception):
        def __str__(self):
            return "SECRET-CONTENT"

    assert e2e_status._safe_error(SecretError("SECRET-CONTENT")) == "SecretError"
