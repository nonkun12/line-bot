import agents.sheets.autonomous_ledger as ledger


SHEET = "AutonomousDevelopment"
LEDGER_START = 30  # AE, zero-based within A:ZZ
LEDGER_RANGE = "AutonomousDevelopment!AE:AU"


class FakeClient:
    def __init__(self, existing=None, response=None, readback=None, titles=None):
        self.existing = existing or []
        self.response = response or {
            "updates": {"updatedRows": 1, "updatedRange": f"{SHEET}!AE185:AU185"}
        }
        self.readback = readback
        self.appended = []
        self.read_ranges = []
        self.titles = titles or [SHEET]
        self.sheet_title_calls = 0

    def sheet_titles(self):
        self.sheet_title_calls += 1
        return self.titles

    def _header_row(self):
        return [""] * LEDGER_START + ledger.HEADERS

    def read_rows(self, range_name):
        self.read_ranges.append(range_name)
        if range_name in (
            f"{SHEET}!A1:ZZ1000",
            f"'{SHEET}'!A1:ZZ1000",
            *[f"'{title}'!A1:ZZ1000" for title in self.titles],
        ):
            return [self._header_row(), *self.existing]
        match = range_name in (f"{SHEET}!AE185:AU185", f"'{SHEET}'!AE185:AU185", *[f"'{title}'!AE185:AU185" for title in self.titles])
        if match and self.readback is not None:
            return self.readback
        return []

    def update_row(self, *args):
        return {"updatedRows": 1}

    def append_row(self, *args):
        self.appended.append(args)
        return self.response


def make_record(run_id="123"):
    return ledger.AutonomousRunRecord(
        timestamp="2026-09-23T03:00:00Z",
        run_id=run_id,
        task_id="scheduled-distributed-development",
        source="scheduler",
        agent="DistributedDevelopmentRuntime",
        task_summary="test",
        base_sha="base",
        produced_sha="produced",
        changed_files="app.py",
        pr_url="",
        tests_result="FAIL",
        verification_result="NOT_RUN",
        safety_gate_result="BLOCKED",
        merge_result="NOT_AUTO_MERGED",
        blocked_failed_reason="provider_error",
        next_action="review_failure",
    )


def ledger_row(values):
    return [""] * LEDGER_START + values


def configure_record_env(monkeypatch, record):
    values = {
        "GITHUB_RUN_ID": record.run_id,
        "AUTONOMOUS_TIMESTAMP": record.timestamp,
        "AUTONOMOUS_TASK_ID": record.task_id,
        "AUTONOMOUS_SOURCE": record.source,
        "AUTONOMOUS_AGENT": record.agent,
        "DEV_INSTRUCTION": record.task_summary,
        "AUTONOMOUS_START_SHA": record.base_sha,
        "AUTONOMOUS_PRODUCED_SHA": record.produced_sha,
        "AUTONOMOUS_CHANGED_FILES": record.changed_files,
        "AUTONOMOUS_PR_URL": record.pr_url,
        "AUTONOMOUS_TESTS_RESULT": record.tests_result,
        "AUTONOMOUS_VERIFICATION_RESULT": record.verification_result,
        "AUTONOMOUS_SAFETY_GATE_RESULT": record.safety_gate_result,
        "AUTONOMOUS_MERGE_RESULT": record.merge_result,
        "AUTONOMOUS_BLOCKED_FAILED_REASON": record.blocked_failed_reason,
        "AUTONOMOUS_NEXT_ACTION": record.next_action,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_append_once_accepts_google_table_location_shift():
    record = make_record()
    client = FakeClient(readback=[record.values()])
    assert ledger.append_once(client, record) is True
    assert client.appended[0][0] == f"'{SHEET}'!AE:AU"
    assert f"'{SHEET}'!A1:ZZ1000" in client.read_ranges
    assert f"{SHEET}!AE185:AU185" in client.read_ranges
    assert client.sheet_title_calls == 1


def test_append_once_resolves_unique_normalized_tab_name_once():
    record = make_record()
    client = FakeClient(readback=[record.values()], titles=["Other", "Autonomous Development"], response={"updates": {"updatedRows": 1, "updatedRange": "'Autonomous Development'!AE185:AU185"}})
    assert ledger.append_once(client, record) is True
    assert client.appended[0][0] == "'Autonomous Development'!AE:AU"
    assert client.sheet_title_calls == 1


def test_resolved_sheet_fails_closed_for_missing_or_ambiguous_match():
    for titles in (["Other"], ["Autonomous Development", "Autonomous-Development"]):
        client = FakeClient(titles=titles)
        try:
            ledger.append_once(client, make_record())
        except RuntimeError as exc:
            assert "tab" in str(exc).lower()
        else:
            raise AssertionError("expected RuntimeError")
        assert client.appended == []

def test_append_once_is_idempotent_only_for_matching_existing_row():
    record = make_record("123")
    client = FakeClient(existing=[ledger_row(record.values())])
    assert ledger.append_once(client, record) is False
    assert client.appended == []


def test_append_once_fails_closed_for_conflicting_existing_run_id():
    record = make_record("123")
    conflicting = record.values()
    conflicting[7] = "different-sha"
    client = FakeClient(existing=[ledger_row(conflicting)])
    try:
        ledger.append_once(client, record)
    except RuntimeError as exc:
        assert "mismatched ledger data" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_append_once_rejects_unconfirmed_append():
    client = FakeClient(response={"updates": {"updatedRows": 0}})
    try:
        ledger.append_once(client, make_record("456"))
    except RuntimeError as exc:
        assert "updatedRows=0" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_append_once_rejects_missing_updated_range():
    client = FakeClient(response={"updates": {"updatedRows": 1}})
    try:
        ledger.append_once(client, make_record("457"))
    except RuntimeError as exc:
        assert "updatedRange" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_append_once_rejects_wrong_width():
    record = make_record("459")
    client = FakeClient(
        response={
            "updates": {
                "updatedRows": 1,
                "updatedRange": f"{SHEET}!AE185:AT185",
            }
        },
        readback=[record.values()],
    )
    try:
        ledger.append_once(client, record)
    except RuntimeError as exc:
        assert "column width" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_append_once_rejects_readback_mismatch():
    record = make_record("458")
    wrong = record.values()
    wrong[12] = "PASS"
    client = FakeClient(readback=[wrong])
    try:
        ledger.append_once(client, record)
    except RuntimeError as exc:
        assert "read-back mismatch" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_record_autonomous_run_retries_once_after_constructor_failure(monkeypatch):
    record = make_record("789")
    configure_record_env(monkeypatch, record)
    expected = ledger.build_record_from_env()
    calls = []

    class Factory:
        def __call__(self):
            calls.append(len(calls))
            if len(calls) == 1:
                raise RuntimeError("temporary Sheets failure")
            return FakeClient(readback=[expected.values()])

    monkeypatch.setattr(ledger, "GoogleSheetsClient", Factory())
    assert ledger.record_autonomous_run() is True
    assert calls == [0, 1]


def test_record_autonomous_run_deduplicates_after_append_then_client_error(monkeypatch):
    record = make_record("790")
    configure_record_env(monkeypatch, record)
    expected = ledger.build_record_from_env()
    shared_rows = []

    class Client:
        def __init__(self, fail_after_append=False):
            self.fail_after_append = fail_after_append

        def sheet_titles(self):
            return [SHEET]

        def read_rows(self, range_name):
            if range_name in (f"{SHEET}!A1:ZZ1000", f"'{SHEET}'!A1:ZZ1000"):
                return [
                    [""] * LEDGER_START + ledger.HEADERS,
                    *shared_rows,
                ]
            if range_name == f"{SHEET}!AE185:AU185" and shared_rows:
                return [expected.values()]
            return []

        def append_row(self, *args):
            shared_rows[:] = [ledger_row(expected.values())]
            if self.fail_after_append:
                raise RuntimeError("response lost after server-side append")
            return {
                "updates": {
                    "updatedRows": 1,
                    "updatedRange": f"{SHEET}!AE185:AU185",
                }
            }

    calls = []

    class Factory:
        def __call__(self):
            client = Client(fail_after_append=(len(calls) == 0))
            calls.append(client)
            return client

    monkeypatch.setattr(ledger, "GoogleSheetsClient", Factory())
    assert ledger.record_autonomous_run() is False
    assert len(calls) == 2
    assert shared_rows == [ledger_row(expected.values())]
