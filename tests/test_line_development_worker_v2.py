import json

import scripts.line_development_worker_v2 as worker


class _Message:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Response:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)

    def create(self, **kwargs):
        return _Response(self.responses.pop(0))


class FakeClient:
    def __init__(self, responses):
        self.chat = type("Chat", (), {"completions": FakeCompletions(responses)})()


def test_protected_worker_files_are_never_editable():
    assert worker.is_protected("scripts/line_development_worker_v2.py")
    assert worker.is_protected(".github/workflows/line-development.yml")
    assert worker.is_protected("config.py")
    assert not worker.is_protected("app.py")


def test_choose_file_rejects_unknown_path():
    client = FakeClient([json.dumps({"file": "missing.py"})])
    assert worker.choose_file(client, "test", ["app.py"]) is None


def test_find_explicit_targets_selects_named_safe_file_without_ai():
    files = ["README.md", "app.py"]
    assert worker.find_explicit_targets("README.md の先頭を更新", files) == ["README.md"]


def test_choose_file_uses_explicit_safe_target_before_ai():
    client = FakeClient([json.dumps({"file": None})])
    assert worker.choose_file(client, "README.md の先頭を更新", ["README.md", "app.py"]) == "README.md"
    assert client.chat.completions.responses == [json.dumps({"file": None})]


def test_find_explicit_targets_excludes_protected_files():
    files = [".github/workflows/line-development.yml", "app.py"]
    assert worker.find_explicit_targets(".github/workflows/line-development.yml を変更", files) == []


def test_find_explicit_targets_rejects_multiple_named_files():
    files = ["README.md", "app.py"]
    assert worker.find_explicit_targets("README.md と app.py を変更", files) == ["README.md", "app.py"]


def test_validate_plan_rejects_change_outside_selected_file():
    plan = {"no_change": False, "changes": [{"file": "README.md", "old": "a", "new": "b"}]}
    assert worker.validate_plan(plan, "app.py") == (False, "change_outside_selected_file")


def test_validate_plan_accepts_no_change():
    assert worker.validate_plan({"no_change": True}, "app.py") == (True, "no_change")


def test_apply_plan_requires_unique_anchor(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    target = tmp_path / "app.py"
    target.write_text("x\nx\n", encoding="utf-8")
    plan = {"no_change": False, "changes": [{"file": "app.py", "old": "x", "new": "y"}]}
    ok, detail, touched = worker.apply_plan(plan)
    assert not ok
    assert detail == "anchor_count_app.py:2"
    assert touched == []
    assert target.read_text(encoding="utf-8") == "x\nx\n"


def test_apply_plan_changes_one_exact_anchor(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    target = tmp_path / "app.py"
    target.write_text("before\nTARGET\nafter\n", encoding="utf-8")
    plan = {"no_change": False, "changes": [{"file": "app.py", "old": "TARGET", "new": "REPLACED"}]}
    ok, detail, touched = worker.apply_plan(plan)
    assert ok and detail == "applied"
    assert touched == ["app.py"]
    assert "REPLACED" in target.read_text(encoding="utf-8")
