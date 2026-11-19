import scripts.line_development_worker_v2 as worker


def test_python_compile_failure_is_detected():
    output = "py_compile tests/test_example.py: returncode=1\nIndentationError: expected an indented block"
    assert worker.has_python_compile_failure(output)


def test_successful_compile_does_not_trigger_fail_closed_path():
    output = "py_compile tests/test_example.py: returncode=0\nfull pytest:\n1 passed"
    assert not worker.has_python_compile_failure(output)


def test_unrelated_pytest_failure_does_not_count_as_compile_failure():
    output = "full pytest:\n1 failed, 3 passed"
    assert not worker.has_python_compile_failure(output)
