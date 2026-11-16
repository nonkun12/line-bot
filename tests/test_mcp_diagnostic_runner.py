from mcp_diagnostic_runner import McpDiagnosticRunner, format_mcp_diagnostic_report


class FakeExecutor:
    def __init__(self):
        self.tasks = []

    def submit(self, fn, *args):
        self.tasks.append((fn, args))
        return None

    def run_next(self):
        fn, args = self.tasks.pop(0)
        fn(*args)


def _report():
    return {
        "health": "PASS",
        "ready": "PASS",
        "mcp_auth": "PASS",
        "tools_list": "PASS",
        "tool_count": 3,
        "elapsed_ms": 123,
        "status": "PASS",
    }


def test_runner_returns_without_running_diagnostic_and_pushes_result_later():
    executor = FakeExecutor()
    runner = McpDiagnosticRunner(executor=executor)
    calls = []
    pushed = []

    def diagnose():
        calls.append("diagnose")
        return _report()

    assert runner.submit("U123", diagnose, lambda user, text: pushed.append((user, text)))
    assert calls == []
    assert pushed == []
    assert len(executor.tasks) == 1

    executor.run_next()

    assert calls == ["diagnose"]
    assert len(pushed) == 1
    assert pushed[0][0] == "U123"
    assert "総合判定: PASS" in pushed[0][1]


def test_runner_allows_only_one_in_flight_diagnostic():
    executor = FakeExecutor()
    runner = McpDiagnosticRunner(executor=executor)
    pushed = []

    assert runner.submit("U123", _report, lambda user, text: pushed.append(text))
    assert not runner.submit("U123", _report, lambda user, text: pushed.append(text))

    executor.run_next()

    assert len(pushed) == 1
    assert runner.submit("U123", _report, lambda user, text: pushed.append(text))


def test_runner_sends_safe_failure_notification():
    executor = FakeExecutor()
    runner = McpDiagnosticRunner(executor=executor)
    pushed = []

    def fail():
        raise RuntimeError("secret details must not reach LINE")

    assert runner.submit("U123", fail, lambda user, text: pushed.append((user, text)))
    executor.run_next()

    assert len(pushed) == 1
    assert pushed[0][0] == "U123"
    assert "失敗しました" in pushed[0][1]
    assert "secret details" not in pushed[0][1]


def test_format_mcp_diagnostic_report_includes_read_only_result():
    rendered = format_mcp_diagnostic_report(_report())
    assert "MCP接続診断（読み取り専用）" in rendered
    assert "ツール数: 3" in rendered
    assert "総合判定: PASS" in rendered
