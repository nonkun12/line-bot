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


def test_test_instruction_requires_no_file_target():
    assert worker.is_test_instruction("開発接続テスト")
    assert worker.is_test_instruction("接続テスト")
    assert worker.is_test_instruction("動作確認")
    assert worker.is_test_instruction("疎通確認")
    assert worker.is_test_instruction("workflow-test")
    assert worker.is_test_instruction("connection test")
    assert not worker.is_test_instruction("app.pyのバグを修正")
    assert not worker.is_test_instruction(
        "scripts/line_development.py に「LINE自動開発テスト」のコメントを1行追加して"
    )
    assert not worker.is_test_instruction(
        "README.md に「自動開発テスト」を1行追加して"
    )


def test_choose_file_rejects_unknown_path():
    client = FakeClient([json.dumps({"file": "missing.py"})])
    assert worker.choose_file(client, "test", ["app.py"]) is None


def test_extract_explicit_path_selects_named_safe_file_without_ai():
    files = ["README.md", "app.py"]
    assert worker._extract_explicit_path("README.md の先頭を更新", files) == "README.md"


def test_choose_file_uses_explicit_safe_target_without_ai():
    client = FakeClient([])
    assert worker.choose_file(client, "README.md の先頭を更新", ["README.md", "app.py"]) == "README.md"
    assert client.chat.completions.responses == []


def test_choose_file_falls_back_to_explicit_path_when_llm_returns_null():
    client = FakeClient([json.dumps({"file": None})])
    assert worker.choose_file(client, "README.mdの説明を直して", ["README.md", "app.py"]) == "README.md"


def test_choose_file_falls_back_to_explicit_path_on_invalid_json():
    client = FakeClient(["not json at all"])
    assert worker.choose_file(client, "README.mdを更新して", ["README.md", "app.py"]) == "README.md"


def test_choose_file_fallback_ignores_paths_not_in_allowed_list():
    client = FakeClient([json.dumps({"file": None})])
    assert worker.choose_file(client, "config.pyを直して", ["app.py"]) is None


def test_choose_file_fallback_refuses_ambiguous_multi_file_instructions():
    client = FakeClient([json.dumps({"file": None})])
    assert worker.choose_file(
        client, "app.pyとREADME.mdの両方を更新して", ["app.py", "README.md"]
    ) is None


def test_choose_file_fallback_does_not_override_a_valid_llm_selection():
    client = FakeClient([json.dumps({"file": "app.py"})])
    assert worker.choose_file(
        client, "README.mdも参考にしつつapp.pyを直して", ["app.py", "README.md"]
    ) == "app.py"


def test_choose_file_fallback_ignores_filenames_absent_from_repo():
    client = FakeClient([json.dumps({"file": None})])
    assert worker.choose_file(client, "missing.pyを直して", ["app.py"]) is None


def test_extract_explicit_path_excludes_protected_files():
    files = [".github/workflows/line-development.yml", "app.py"]
    assert worker._extract_explicit_path(".github/workflows/line-development.yml を変更", files) is None


def test_extract_explicit_path_rejects_multiple_named_files():
    files = ["README.md", "app.py"]
    assert worker._extract_explicit_path("README.md と app.py を変更", files) is None


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
