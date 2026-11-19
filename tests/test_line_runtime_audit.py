from core import line_runtime_audit


def test_record_line_runtime_writes_roles_and_route(monkeypatch):
    calls = []

    class Writer:
        def append_development_result(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(
        line_runtime_audit.GoogleSheetsWriter,
        "from_environment",
        classmethod(lambda cls: Writer()),
    )
    line_runtime_audit.record_line_runtime(
        user_message="AI NEWSとトヨタ（7203）の最新情報を調べて",
        reply="news result",
        status="PASS",
        route="management",
    )
    assert calls[0]["branch"] == "line-runtime"
    # This message is an AI NEWS request; the stock specialist requires an
    # explicit stock term such as 株/株価/銘柄 or an English stock keyword.
    assert "roles=news" in calls[0]["detail"]
    assert "route=management" in calls[0]["detail"]


def test_record_line_runtime_does_not_raise_when_sheets_is_unconfigured(monkeypatch):
    monkeypatch.setattr(
        line_runtime_audit.GoogleSheetsWriter,
        "from_environment",
        classmethod(lambda cls: None),
    )
    line_runtime_audit.record_line_runtime(
        user_message="hello", reply="ok", status="PASS", route="core-gateway"
    )
