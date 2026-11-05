import json
import os
import subprocess
import sys

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


def test_ask_uses_low_reasoning_effort_by_default(monkeypatch):
    monkeypatch.delenv("DEV_AI_REASONING_EFFORT", raising=False)
    captured = {}

    class CaptureCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _Response("ok")

    client = type("Client", (), {"chat": type("Chat", (), {"completions": CaptureCompletions()})()})()

    assert worker.ask(client, "system", "prompt") == "ok"
    assert captured["reasoning_effort"] == "low"


def test_append_only_test_generation_uses_reasoning_completion_budget(monkeypatch, tmp_path):
    target = tmp_path / "tests" / "test_sample.py"
    target.parent.mkdir()
    original = "def test_existing_contract():\n    assert True\n"
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    captured = {}

    class CaptureCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _Response("def test_new_boundary():\n    assert True\n")

    client = type("Client", (), {"chat": type("Chat", (), {"completions": CaptureCompletions()})()})()
    plan, error = worker.build_append_only_test_plan(
        client, "Add one focused boundary regression", "tests/test_sample.py", original
    )

    assert error == ""
    assert plan is not None
    assert captured["max_completion_tokens"] == worker.MAX_APPEND_ONLY_RESPONSE_TOKENS
    assert captured["reasoning_effort"] == "low"
    assert "max_tokens" not in captured
    assert "response_format" not in captured





def test_append_only_test_generation_bounds_context_before_larger_completion(monkeypatch, tmp_path):
    target = tmp_path / "tests" / "test_sample.py"
    target.parent.mkdir()
    original = "def test_existing_contract():\n    assert True\n"
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    captured = {}

    class CaptureCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _Response("def test_new_boundary():\n    assert True\n")

    client = type("Client", (), {"chat": type("Chat", (), {"completions": CaptureCompletions()})()})()
    oversized_context = "HEAD\n" + ("x" * 9000) + "\nTAIL"
    plan, error = worker.build_append_only_test_plan(
        client, "Add one focused boundary regression", "tests/test_sample.py",
        oversized_context,
    )

    assert error == ""
    assert plan is not None
    prompt = captured["messages"][1]["content"]
    assert len(prompt) < worker.MAX_APPEND_ONLY_CONTEXT_CHARS + 1000
    assert "HEAD" in prompt and "TAIL" in prompt
    assert "append-only context bounded" in prompt
    assert captured["max_completion_tokens"] == worker.MAX_APPEND_ONLY_RESPONSE_TOKENS


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


def test_choose_file_routes_operational_validation_to_e2e_harness(monkeypatch):
    def forbidden_ask(*args, **kwargs):
        raise AssertionError("operational validation must not use generic model file selection")

    monkeypatch.setattr(worker, "ask", forbidden_ask)
    files = [
        "core/line_development_runtime.py",
        "tests/test_line_development.py",
        "tests/test_app_development_dispatch.py",
    ]

    for instruction in (
        "LINE AI Secretaryの自動開発基盤を実運用テストしてください",
        "自動開発基盤の実運用検証をしてください",
        "分散AI基盤検証を実施してください",
    ):
        assert worker.choose_file(FakeClient([]), instruction, files) == (
            "tests/test_line_development.py"
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


def test_validate_plan_rejects_protected_selected_file():
    plan = {"no_change": False, "changes": [{"file": "line_development.py", "old": "a", "new": "b"}]}
    assert worker.validate_plan(plan, "line_development.py") == (
        False,
        "protected_file:line_development.py",
    )


def test_validate_plan_rejects_standalone_diff_markers_in_replacement():
    plan = {
        "no_change": False,
        "changes": [{"file": "app.py", "old": "x", "new": "safe\n+\nchange"}],
    }
    assert worker.validate_plan(plan, "app.py") == (
        False,
        "diff_marker_in_replacement",
    )


def test_validate_plan_accepts_no_change():
    assert worker.validate_plan({"no_change": True}, "app.py") == (True, "no_change")


def test_repair_anchor_plan_receives_ambiguity_and_returns_plan():
    rejected = {
        "no_change": False,
        "changes": [{"file": "app.py", "old": "TARGET", "new": "REPLACED"}],
    }
    response = json.dumps(
        {
            "no_change": False,
            "changes": [
                {
                    "file": "app.py",
                    "old": "def target():\n    TARGET\n    return True\n",
                    "new": "def target():\n    REPLACED\n    return True\n",
                }
            ],
        }
    )
    client = FakeClient([response])

    plan = worker.repair_anchor_plan(
        client,
        "app.py の対象を修正",
        "app.py",
        "def target():\n    TARGET\n    return True\n",
        rejected,
        "anchor_count_app.py:2",
    )

    assert plan["changes"][0]["old"].count("TARGET") == 1

def test_repair_size_plan_returns_small_edit():
    rejected = {
        "no_change": False,
        "changes": [{"file": "app.py", "old": "old", "new": "x" * 2000}],
    }
    response = json.dumps(
        {
            "no_change": False,
            "changes": [
                {
                    "file": "app.py",
                    "old": "def target():\n    old\n",
                    "new": "def target():\n    new\n",
                }
            ],
        }
    )
    client = FakeClient([response])

    plan = worker.repair_size_plan(
        client,
        "app.py の対象を最小修正",
        "app.py",
        "def target():\n    old\n",
        rejected,
        "change_too_large_new",
    )

    assert worker.validate_plan(plan, "app.py") == (True, "app.py")


def test_validate_plan_with_bounded_repairs_calls_size_repair_once():
    chosen = "tests/test_management_router.py"
    rejected = {
        "no_change": False,
        "changes": [{"file": chosen, "old": "old", "new": "x" * 2000}],
    }
    response = json.dumps(
        {
            "no_change": False,
            "changes": [
                {"file": chosen, "old": "def target():\n    old\n", "new": "def target():\n    new\n"}
            ],
        }
    )
    client = FakeClient([response])

    plan, ok, detail = worker.validate_plan_with_bounded_repairs(
        client,
        "テストを最小修正",
        chosen,
        rejected,
        "def target():\n    old\n",
    )

    assert ok
    assert detail == chosen
    assert plan["changes"][0]["new"] == "def target():\n    new\n"



def test_apply_plan_with_bounded_anchor_repair_recovers_once(monkeypatch, tmp_path):
    target = tmp_path / "app.py"
    target.write_text("exact\n", encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    rejected = {
        "no_change": False,
        "changes": [{"file": "app.py", "old": "missing", "new": "replacement"}],
    }
    repaired = {
        "no_change": False,
        "changes": [{"file": "app.py", "old": "exact", "new": "replacement"}],
    }
    calls = []

    client = FakeClient([])
    monkeypatch.setattr(worker, "repair_anchor_plan", lambda *args: calls.append("repair") or repaired)

    plan, ok, detail, touched = worker.apply_plan_with_bounded_anchor_repair(
        client,
        "app.py を最小修正",
        "app.py",
        rejected,
        "exact\n",
    )

    assert ok
    assert detail == "applied"
    assert touched == ["app.py"]
    assert calls == ["repair"]
    assert plan == repaired
    assert target.read_text(encoding="utf-8") == "replacement\n"


def test_apply_plan_with_bounded_anchor_repair_size_repairs_once(monkeypatch, tmp_path):
    target = tmp_path / "app.py"
    target.write_text("exact\\n", encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    rejected = {
        "no_change": False,
        "changes": [{"file": "app.py", "old": "missing", "new": "replacement"}],
    }
    oversized = {
        "no_change": False,
        "changes": [{"file": "app.py", "old": "exact", "new": "x" * 2000}],
    }
    repaired = {
        "no_change": False,
        "changes": [{"file": "app.py", "old": "exact", "new": "replacement"}],
    }
    calls = []
    monkeypatch.setattr(worker, "repair_anchor_plan", lambda *args: oversized)
    monkeypatch.setattr(
        worker,
        "repair_size_plan",
        lambda *args: calls.append("size") or repaired,
    )

    plan, ok, detail, touched = worker.apply_plan_with_bounded_anchor_repair(
        FakeClient([]),
        "app.py を最小修正",
        "app.py",
        rejected,
        "exact\\n",
    )

    assert ok
    assert detail == "applied"
    assert touched == ["app.py"]
    assert calls == ["size"]
    assert plan == repaired
    assert target.read_text(encoding="utf-8") == "replacement\\n"


def test_apply_plan_with_bounded_anchor_repair_rejects_unrepairable_size(monkeypatch, tmp_path):
    target = tmp_path / "app.py"
    original = "exact\\n"
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    rejected = {
        "no_change": False,
        "changes": [{"file": "app.py", "old": "missing", "new": "replacement"}],
    }
    oversized = {
        "no_change": False,
        "changes": [{"file": "app.py", "old": "exact", "new": "x" * 2000}],
    }
    calls = []
    monkeypatch.setattr(worker, "repair_anchor_plan", lambda *args: oversized)
    monkeypatch.setattr(
        worker,
        "repair_size_plan",
        lambda *args: calls.append("size") or oversized,
    )

    plan, ok, detail, touched = worker.apply_plan_with_bounded_anchor_repair(
        FakeClient([]),
        "app.py を最小修正",
        "app.py",
        rejected,
        original,
    )

    assert not ok
    assert detail == "change_too_large"
    assert touched == []
    assert calls == ["size"]
    assert plan == oversized
    assert target.read_text(encoding="utf-8") == original


def test_apply_plan_with_bounded_anchor_size_repair_rejects_no_change(monkeypatch, tmp_path):
    target = tmp_path / "app.py"
    original = "exact\\n"
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    rejected = {"no_change": False, "changes": [{"file": "app.py", "old": "missing", "new": "x"}]}
    oversized = {"no_change": False, "changes": [{"file": "app.py", "old": "exact", "new": "x" * 2000}]}
    no_change = {"no_change": True, "changes": []}
    calls = []
    monkeypatch.setattr(worker, "repair_anchor_plan", lambda *args: oversized)
    monkeypatch.setattr(worker, "repair_size_plan", lambda *args: calls.append("size") or no_change)

    plan, ok, detail, touched = worker.apply_plan_with_bounded_anchor_repair(
        FakeClient([]), "app.py を最小修正", "app.py", rejected, original
    )

    assert not ok
    assert detail == "no_change"
    assert touched == []
    assert calls == ["size"]
    assert plan == no_change
    assert target.read_text(encoding="utf-8") == original


def test_apply_plan_with_bounded_anchor_size_repair_rejects_invalid_file(monkeypatch, tmp_path):
    target = tmp_path / "app.py"
    original = "exact\\n"
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    rejected = {"no_change": False, "changes": [{"file": "app.py", "old": "missing", "new": "x"}]}
    oversized = {"no_change": False, "changes": [{"file": "app.py", "old": "exact", "new": "x" * 2000}]}
    invalid = {"no_change": False, "changes": [{"file": "other.py", "old": "a", "new": "b"}]}
    calls = []
    monkeypatch.setattr(worker, "repair_anchor_plan", lambda *args: oversized)
    monkeypatch.setattr(worker, "repair_size_plan", lambda *args: calls.append("size") or invalid)

    plan, ok, detail, touched = worker.apply_plan_with_bounded_anchor_repair(
        FakeClient([]), "app.py を最小修正", "app.py", rejected, original
    )

    assert not ok
    assert detail == "change_outside_selected_file"
    assert touched == []
    assert calls == ["size"]
    assert plan == invalid
    assert target.read_text(encoding="utf-8") == original


def test_apply_plan_with_bounded_anchor_repair_retries_non_unique_anchor(monkeypatch, tmp_path):
    target = tmp_path / "app.py"
    target.write_text("x\nx\nexact\n", encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    rejected = {
        "no_change": False,
        "changes": [{"file": "app.py", "old": "missing", "new": "replacement"}],
    }
    ambiguous = {
        "no_change": False,
        "changes": [{"file": "app.py", "old": "x", "new": "y"}],
    }
    repaired = {
        "no_change": False,
        "changes": [{"file": "app.py", "old": "exact", "new": "replacement"}],
    }
    calls = []

    client = FakeClient([])
    def repair(*args):
        calls.append("repair")
        return ambiguous if len(calls) == 1 else repaired
    monkeypatch.setattr(worker, "repair_anchor_plan", repair)

    plan, ok, detail, touched = worker.apply_plan_with_bounded_anchor_repair(
        client,
        "app.py を最小修正",
        "app.py",
        rejected,
        "x\nx\nexact\n",
    )

    assert ok
    assert detail == "applied"
    assert touched == ["app.py"]
    assert calls == ["repair", "repair"]
    assert plan == repaired
    assert target.read_text(encoding="utf-8") == "x\nx\nreplacement\n"



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


def test_run_tests_executes_full_pytest_suite(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, timeout=900, input_text=None):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(worker, "ROOT", tmp_path)
    monkeypatch.setattr(worker, "run", fake_run)

    passed, output = worker.run_tests([])

    assert passed
    assert any(cmd[:4] == [worker.sys.executable, "-m", "pytest", "-q"] for cmd in calls)
    pytest_call = next(cmd for cmd in calls if cmd[2:] == ["pytest", "-q", "--tb=native"])
    assert pytest_call == [worker.sys.executable, "-m", "pytest", "-q", "--tb=native"]
    assert "full pytest:" in output


def test_run_tests_can_verify_only_allowlisted_target_for_no_change(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, timeout=900, input_text=None):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="1 passed", stderr="")

    monkeypatch.setattr(worker, "ROOT", tmp_path)
    monkeypatch.setattr(worker, "run", fake_run)

    passed, output = worker.run_tests(["tests/test_ai_speaker.py"], full_suite=False)

    assert passed
    pytest_call = next(cmd for cmd in calls if cmd[2:] and cmd[2] == "pytest")
    assert pytest_call == [
        worker.sys.executable, "-m", "pytest", "-q", "--tb=native",
        "tests/test_ai_speaker.py",
    ]
    assert "targeted pytest:" in output


def test_worker_entrypoint_is_executable():
    env = os.environ.copy()
    env.pop("DEV_INSTRUCTION", None)
    env.pop("GROQ_API_KEY", None)
    proc = subprocess.run(
        [sys.executable, "scripts/line_development_worker_v2.py"],
        cwd=worker.ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert proc.returncode == 2
    assert "No development instruction supplied." in proc.stdout


def test_build_plan_system_prompt_constrains_to_selected_file_and_diff_markers(monkeypatch):
    recorded = {}

    def fake_ask(client, system, prompt, max_tokens=1024):
        recorded["system"] = system
        recorded["prompt"] = prompt
        return json.dumps({"no_change": True})

    monkeypatch.setattr(worker, "ask", fake_ask)
    client = FakeClient([])
    chosen = "uhip/tests/test_schema_contracts.py"

    plan = worker.build_plan(client, "テストを追加して", chosen, "context_text")

    assert plan == {"no_change": True}
    sys_prompt = recorded["system"]
    assert f"The ONLY editable file is: {chosen}" in sys_prompt
    assert f'changes[0]["file"] must be exactly "{chosen}"' in sys_prompt
    assert "The new field is replacement text only" in sys_prompt
    assert "never include unified-diff markers" in sys_prompt
    assert 'return {"no_change":true}' in sys_prompt
    user_prompt = recorded["prompt"]
    assert f"Selected file (ONLY editable file):\n{chosen}" in user_prompt


def test_context_for_preserves_both_ends_with_small_size_overflow(monkeypatch, tmp_path):
    content = "HEAD-MARKER\n" + ("x" * (worker.MAX_FILE_CHARS + 100)) + "\nTAIL-MARKER\n"
    target = tmp_path / "sample.py"
    target.write_text(content, encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    context = worker.context_for("sample.py")

    assert len(context) <= worker.MAX_FILE_CHARS
    assert context.startswith("HEAD-MARKER\n")
    assert "middle omitted; context bounded" in context
    assert context.endswith("TAIL-MARKER\n")


def test_context_for_keeps_both_ends_when_file_is_far_over_limit(monkeypatch, tmp_path):
    content = "HEAD-MARKER\n" + ("x" * (worker.MAX_FILE_CHARS + 10000)) + "\nTAIL-MARKER\n"
    target = tmp_path / "sample.py"
    target.write_text(content, encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    context = worker.context_for("sample.py")

    assert len(context) <= worker.MAX_FILE_CHARS
    assert context.startswith("HEAD-MARKER\n")
    assert "middle omitted; context bounded" in context
    assert context.endswith("TAIL-MARKER\n")



def test_repair_invalid_old_new_plan_accepts_validation_error(monkeypatch):
    captured = {}

    def fake_ask(client, system, prompt, max_tokens):
        captured["prompt"] = prompt
        return json.dumps({"no_change": True})

    monkeypatch.setattr(worker, "ask", fake_ask)
    result = worker.repair_invalid_old_new_plan(
        FakeClient([]),
        "instruction",
        "app.py",
        "current context",
        {"malformed": True},
        "invalid_old_new",
    )

    assert result == {"no_change": True}
    assert "Validation error:\ninvalid_old_new" in captured["prompt"]


def test_validate_plan_with_bounded_repairs_recovers_invalid_old_new_once(monkeypatch):
    chosen = "tests/test_management_router.py"
    rejected = {
        "no_change": False,
        "changes": [{"file": chosen, "old": None, "new": "replacement"}],
    }
    repaired = {
        "no_change": False,
        "changes": [
            {
                "file": chosen,
                "old": "def target():\\n    old\\n",
                "new": "def target():\\n    new\\n",
            }
        ],
    }
    calls = []
    monkeypatch.setattr(
        worker,
        "repair_invalid_old_new_plan",
        lambda *args: calls.append("repair") or repaired,
    )

    plan, ok, detail = worker.validate_plan_with_bounded_repairs(
        FakeClient([]),
        "テストを最小修正",
        chosen,
        rejected,
        "def target():\\n    old\\n",
    )

    assert ok
    assert detail == chosen
    assert plan == repaired
    assert calls == ["repair"]


def test_validate_plan_with_bounded_repairs_rejects_unsafe_invalid_old_new_repair(monkeypatch):
    chosen = "tests/test_management_router.py"
    rejected = {
        "no_change": False,
        "changes": [{"file": chosen, "old": None, "new": "replacement"}],
    }
    unsafe = {
        "no_change": False,
        "changes": [{"file": "app.py", "old": "old", "new": "new"}],
    }
    calls = []
    monkeypatch.setattr(
        worker,
        "repair_invalid_old_new_plan",
        lambda *args: calls.append("repair") or unsafe,
    )

    plan, ok, detail = worker.validate_plan_with_bounded_repairs(
        FakeClient([]),
        "テストを最小修正",
        chosen,
        rejected,
        "def target():\\n    old\\n",
    )

    assert not ok
    assert detail == "change_outside_selected_file"
    assert plan == rejected
    assert calls == ["repair"]


def test_not_run_queue_regression_task_uses_deterministic_target():
    from core.line_development_runtime import _DETERMINISTIC_AUTONOMOUS_TASK_TARGETS

    assert _DETERMINISTIC_AUTONOMOUS_TASK_TARGETS[
        "continuous-loop-not-run-does-not-continue-regression"
    ] == "tests/test_continuous_distributed_loop_workflow.py"

    from core.line_development_runtime import _deterministic_autonomous_test_plan

    plan, error = _deterministic_autonomous_test_plan(
        "tests/test_continuous_distributed_loop_workflow.py",
        "continuous-loop-not-run-does-not-continue-regression",
    )
    assert error is None
    assert plan is not None
    assert plan["source"] == "deterministic_autonomous_task"
    assert plan["no_change"] is True

def test_queue_progress_not_run_task_uses_deterministic_target():
    from core.line_development_runtime import _DETERMINISTIC_AUTONOMOUS_TASK_TARGETS

    task_id = "queue-progress-excludes-not-run-results-regression"
    target = "tests/test_distributed_loop_queue_progress.py"
    assert _DETERMINISTIC_AUTONOMOUS_TASK_TARGETS[task_id] == target

    from core.line_development_runtime import _deterministic_autonomous_test_plan

    plan, error = _deterministic_autonomous_test_plan(target, task_id)
    assert error is None
    assert plan is not None
    assert plan["source"] == "deterministic_autonomous_task"
    if plan["no_change"]:
        # The autonomous worker may already have applied the guarded test before pytest.
        assert "def test_progress_does_not_count_not_run_result_as_completion(" in open(
            "tests/test_distributed_loop_queue_progress.py", encoding="utf-8"
        ).read()
    else:
        assert "test_progress_does_not_count_not_run_result_as_completion" in plan["changes"][0]["new"]



def test_default_completion_budget_preserves_groq_free_tpm_headroom():
    # The Groq free/on-demand TPM ceiling includes both prompt and completion.
    # Keep enough headroom that a ~4.8k-token prompt is not rejected at 8k TPM.
    assert worker.MAX_RESPONSE_TOKENS == 2500


def test_repair_invalid_change_count_plan_requests_single_change(monkeypatch):
    chosen = "tests/test_example.py"
    rejected = {"no_change": False, "changes": []}
    repaired = {
        "no_change": False,
        "changes": [{"file": chosen, "old": "def test_old():\n    pass\n", "new": "def test_new():\n    pass\n"}],
    }
    captured = {}

    def fake_ask(client, system, prompt, max_tokens):
        captured["system"] = system
        captured["prompt"] = prompt
        return json.dumps(repaired)

    monkeypatch.setattr(worker, "ask", fake_ask)
    result = worker.repair_invalid_change_count_plan(
        FakeClient([]), "Add one regression test", chosen, "def test_old():\n    pass\n", rejected
    )

    assert result == repaired
    assert "exactly one changes object" in captured["system"]
    assert chosen in captured["prompt"]
    assert "invalid_change_count" in captured["prompt"]


def test_bounded_repairs_recovers_invalid_change_count_once(monkeypatch):
    chosen = "tests/test_management_router.py"
    rejected = {"no_change": False, "changes": []}
    repaired = {
        "no_change": False,
        "changes": [{"file": chosen, "old": "old", "new": "new"}],
    }
    calls = []
    monkeypatch.setattr(
        worker, "repair_invalid_change_count_plan", lambda *args: calls.append(1) or repaired
    )

    plan, ok, detail = worker.validate_plan_with_bounded_repairs(
        FakeClient([]), "Add one regression test", chosen, rejected, "old"
    )

    assert ok
    assert detail == chosen
    assert plan == repaired
    assert calls == [1]


def test_bounded_repairs_fails_closed_if_invalid_change_count_repair_returns_no_change(monkeypatch):
    chosen = "tests/test_management_router.py"
    rejected = {"no_change": False, "changes": []}
    calls = []
    monkeypatch.setattr(
        worker, "repair_invalid_change_count_plan",
        lambda *args: calls.append(1) or {"no_change": True},
    )

    plan, ok, detail = worker.validate_plan_with_bounded_repairs(
        FakeClient([]), "Add one regression test", chosen, rejected, "old"
    )

    assert not ok
    assert detail == "invalid_change_count_repair_failed"
    assert plan == rejected
    assert calls == [1]


def test_bounded_repairs_rejects_invalid_change_count_repair_for_other_file(monkeypatch):
    chosen = "tests/test_management_router.py"
    rejected = {"no_change": False, "changes": []}
    unsafe = {"no_change": False, "changes": [{"file": "app.py", "old": "old", "new": "new"}]}
    monkeypatch.setattr(worker, "repair_invalid_change_count_plan", lambda *args: unsafe)

    plan, ok, detail = worker.validate_plan_with_bounded_repairs(
        FakeClient([]), "Add one regression test", chosen, rejected, "old"
    )

    assert not ok
    assert detail == "invalid_change_count_repair_failed"
    assert plan == rejected


def test_validate_plan_size_boundaries_are_exact():
    chosen = "app.py"
    accepted = {
        "no_change": False,
        "changes": [{"file": chosen, "old": "o" * 1200, "new": "n" * 1800}],
    }
    too_large_old = {
        "no_change": False,
        "changes": [{"file": chosen, "old": "o" * 1201, "new": "n"}],
    }
    too_large_new = {
        "no_change": False,
        "changes": [{"file": chosen, "old": "o", "new": "n" * 1801}],
    }

    assert worker.validate_plan(accepted, chosen) == (True, chosen)
    assert worker.validate_plan(too_large_old, chosen) == (False, "change_too_large")
    assert worker.validate_plan(too_large_new, chosen) == (False, "change_too_large")


def test_apply_anchor_size_repair_is_used_only_once_across_anchor_retries(monkeypatch, tmp_path):
    target = tmp_path / "app.py"
    original = "x\\nx\\nexact\\n"
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    rejected = {"no_change": False, "changes": [{"file": "app.py", "old": "missing", "new": "replacement"}]}
    oversized = {"no_change": False, "changes": [{"file": "app.py", "old": "exact", "new": "z" * 2000}]}
    size_repaired_but_ambiguous = {"no_change": False, "changes": [{"file": "app.py", "old": "x", "new": "y"}]}
    anchor_calls = []
    size_calls = []

    def repair_anchor(*args):
        anchor_calls.append(1)
        return oversized if len(anchor_calls) == 1 else size_repaired_but_ambiguous

    def repair_size(*args):
        size_calls.append(1)
        return size_repaired_but_ambiguous

    monkeypatch.setattr(worker, "repair_anchor_plan", repair_anchor)
    monkeypatch.setattr(worker, "repair_size_plan", repair_size)

    plan, ok, detail, touched = worker.apply_plan_with_bounded_anchor_repair(
        FakeClient([]), "app.py を最小修正", "app.py", rejected, original
    )

    assert not ok
    assert detail == "anchor_count_app.py:3"
    assert touched == []
    assert len(anchor_calls) == worker.MAX_APPLY_REPAIR_ATTEMPTS
    assert size_calls == [1]
    assert plan == size_repaired_but_ambiguous
    assert target.read_text(encoding="utf-8") == original



def test_test_file_plan_rejects_rewriting_existing_assertions(monkeypatch, tmp_path):
    target = tmp_path / "tests" / "test_sample.py"
    target.parent.mkdir()
    original = "def test_contract():\n    assert route() == 'english'\n"
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    plan = {
        "no_change": False,
        "changes": [{
            "file": "tests/test_sample.py",
            "old": "assert route() == 'english'",
            "new": "assert route() == 'general'",
        }],
    }

    assert worker.validate_plan(plan, "tests/test_sample.py") == (
        False, "existing_test_modified"
    )


def test_test_file_plan_allows_adding_a_new_test_without_changing_existing_tests(monkeypatch, tmp_path):
    target = tmp_path / "tests" / "test_sample.py"
    target.parent.mkdir()
    original = "def test_contract():\n    assert route() == 'english'\n"
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    addition = "\n\ndef test_new_regression():\n    assert route() == 'general'\n"
    plan = {
        "no_change": False,
        "changes": [{
            "file": "tests/test_sample.py",
            "old": original,
            "new": original + addition,
        }],
    }

    assert worker.validate_plan(plan, "tests/test_sample.py") == (
        True, "tests/test_sample.py"
    )



def test_bounded_repair_recovers_rejected_test_rewrite_with_one_additive_test(monkeypatch, tmp_path):
    target = tmp_path / "tests" / "test_sample.py"
    target.parent.mkdir()
    original = "def test_contract():\n    assert route() == 'english'\n"
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    chosen = "tests/test_sample.py"
    rejected = {
        "no_change": False,
        "changes": [{
            "file": chosen,
            "old": "assert route() == 'english'",
            "new": "assert route() == 'general'",
        }],
    }
    addition = "\n\ndef test_new_regression():\n    assert route() == 'general'\n"
    repaired = {
        "no_change": False,
        "changes": [{"file": chosen, "old": original, "new": original + addition}],
    }
    client = FakeClient([json.dumps(repaired)])

    plan, ok, detail = worker.validate_plan_with_bounded_repairs(
        client, "Add one focused regression test", chosen, rejected, original
    )

    assert ok
    assert detail == chosen
    assert plan == repaired
    assert target.read_text(encoding="utf-8") == original
    assert worker._adds_exactly_one_test(chosen, original, original + addition)


def test_bounded_repair_salvages_one_new_test_without_rewriting_existing_tests(monkeypatch, tmp_path):
    target = tmp_path / "tests" / "test_sample.py"
    target.parent.mkdir()
    original = "def test_contract():\n    assert route() == 'english'\n"
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    chosen = "tests/test_sample.py"
    rejected = {
        "no_change": False,
        "changes": [{
            "file": chosen,
            "old": "assert route() == 'english'",
            "new": "assert route() == 'general'",
        }],
    }
    unsafe_repair = {
        "no_change": False,
        "changes": [{
            "file": chosen,
            "old": original,
            "new": (
                "def test_contract():\n    assert route() == 'general'\n"
                "\ndef test_new_regression():\n    assert route() == 'general'\n"
            ),
        }],
    }

    plan, ok, detail = worker.validate_plan_with_bounded_repairs(
        FakeClient([json.dumps(unsafe_repair)]),
        "Add one focused regression test",
        chosen,
        rejected,
        original,
    )

    assert ok
    assert detail == chosen
    change = plan["changes"][0]
    assert change["file"] == chosen
    assert change["new"].endswith("def test_new_regression():\n    assert route() == 'general'\n")
    assert worker._adds_exactly_one_test(chosen, change["old"], change["new"])
    assert target.read_text(encoding="utf-8") == original


def test_additive_test_salvage_rejects_multiple_new_test_functions(monkeypatch, tmp_path):
    target = tmp_path / "tests" / "test_sample.py"
    target.parent.mkdir()
    original = "def test_contract():\n    assert route() == 'english'\n"
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    chosen = "tests/test_sample.py"
    rewritten = {
        "no_change": False,
        "changes": [{
            "file": chosen,
            "old": original,
            "new": (
                "def test_contract():\n    assert route() == 'general'\n"
                "\ndef test_new_one():\n    assert route() == 'general'\n"
                "\ndef test_new_two():\n    assert route() == 'general'\n"
            ),
        }],
    }

    assert worker._salvage_additive_test_plan(chosen, rewritten) is None
    assert target.read_text(encoding="utf-8") == original



def test_append_only_test_plan_constructs_eof_patch_without_rewriting_existing_tests(monkeypatch, tmp_path):
    target = tmp_path / "tests" / "test_sample.py"
    target.parent.mkdir()
    original = "def test_existing_contract():\n    assert normalize(' aapl ') == 'AAPL'\n"
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    generated = "def test_blank_ticker_is_rejected():\n    assert normalize('   ') == ''\n"

    plan, error = worker.build_append_only_test_plan(
        FakeClient([generated]),
        "Add one boundary regression for a blank ticker",
        "tests/test_sample.py",
        original,
    )

    assert error == ""
    assert plan is not None
    assert plan["source"] == "append_only_review_task"
    change = plan["changes"][0]
    assert change["file"] == "tests/test_sample.py"
    assert len(change["old"]) <= 1200
    assert len(change["new"]) <= 1800
    candidate = original.replace(change["old"], change["new"], 1)
    assert candidate.startswith(original)
    assert "def test_blank_ticker_is_rejected():" in candidate
    assert worker.validate_plan(plan, "tests/test_sample.py") == (True, "tests/test_sample.py")
    assert target.read_text(encoding="utf-8") == original


def test_append_only_test_plan_fails_closed_on_imports_and_multiple_functions(monkeypatch, tmp_path):
    target = tmp_path / "tests" / "test_sample.py"
    target.parent.mkdir()
    original = "def test_existing_contract():\n    assert True\n"
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    unsafe = "import os\n\ndef test_reads_environment():\n    assert os.getenv('TOKEN')\n"
    plan, error = worker.build_append_only_test_plan(
        FakeClient([unsafe]),
        "Add a regression test",
        "tests/test_sample.py",
        original,
    )
    assert plan is None
    assert error == "append_only_test_not_single_function"

    multiple = (
        "def test_first():\n    assert True\n\n"
        "def test_second():\n    assert True\n"
    )
    plan, error = worker.build_append_only_test_plan(
        FakeClient([multiple]),
        "Add a regression test",
        "tests/test_sample.py",
        original,
    )
    assert plan is None
    assert error == "append_only_test_not_single_function"
    assert target.read_text(encoding="utf-8") == original



def test_append_only_test_plan_rejects_preimported_process_and_network_modules(monkeypatch, tmp_path):
    target = tmp_path / "tests" / "test_sample.py"
    target.parent.mkdir()
    original = "def test_existing_contract():\n    assert True\n"
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    for generated in (
        "def test_reads_environment():\n    assert os.getenv('TOKEN')\n",
        "def test_starts_process():\n    subprocess.run(['echo', 'unsafe'])\n",
        "def test_calls_network():\n    requests.get('https://example.invalid')\n",
    ):
        plan, error = worker.build_append_only_test_plan(
            FakeClient([generated]),
            "Add a regression test",
            "tests/test_sample.py",
            original,
        )
        assert plan is None
        assert error == "append_only_test_unsafe_operation"

    assert target.read_text(encoding="utf-8") == original




def test_append_only_test_plan_rejects_dunder_attribute_traversal(monkeypatch, tmp_path):
    target = tmp_path / "tests" / "test_sample.py"
    target.parent.mkdir()
    original = "def test_existing_contract():\n    assert True\n"
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    generated = "def test_escapes_restrictions():\n    assert ().__class__.__base__\n"
    plan, error = worker.build_append_only_test_plan(
        FakeClient([generated]),
        "Add a regression test",
        "tests/test_sample.py",
        original,
    )

    assert plan is None
    assert error == "append_only_test_unsafe_operation"
    assert target.read_text(encoding="utf-8") == original


def test_append_only_test_plan_rejects_os_and_filesystem_calls(monkeypatch, tmp_path):
    target = tmp_path / "tests" / "test_sample.py"
    target.parent.mkdir()
    original = "def test_existing_contract():\n    assert True\n"
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    generated = "def test_reads_file():\n    assert open('secret.txt').read()\n"
    plan, error = worker.build_append_only_test_plan(
        FakeClient([generated]),
        "Add a regression test",
        "tests/test_sample.py",
        original,
    )

    assert plan is None
    assert error == "append_only_test_unsafe_operation"
    assert target.read_text(encoding="utf-8") == original



def test_is_test_path_recognizes_root_nested_and_conftest_paths():
    assert worker.is_test_path("test_app.py")
    assert worker.is_test_path("tests/test_app.py")
    assert worker.is_test_path("uhip/tests/test_schema_contracts.py")
    assert worker.is_test_path("pkg/conftest.py")
    assert worker.is_test_path("pkg/sample_test.py")
    assert not worker.is_test_path("core/management_router.py")


def test_choose_file_excludes_tests_from_generic_model_candidates(monkeypatch):
    captured = {}

    def fake_ask(client, system, prompt, max_tokens=1024):
        captured["prompt"] = prompt
        return json.dumps({"file": "core/management_router.py"})

    monkeypatch.setattr(worker, "ask", fake_ask)
    files = [
        "tests/test_management_router.py",
        "uhip/tests/test_schema_contracts.py",
        "core/management_router.py",
    ]

    selected = worker.choose_file(
        FakeClient([]), "一般的なルーティング処理を改善してください", files
    )

    assert selected == "core/management_router.py"
    assert "core/management_router.py" in captured["prompt"]
    assert "tests/test_management_router.py" not in captured["prompt"]
    assert "uhip/tests/test_schema_contracts.py" not in captured["prompt"]


def test_choose_file_fails_closed_when_only_test_candidates_exist(monkeypatch):
    def forbidden_ask(*args, **kwargs):
        raise AssertionError("model must not be asked to select a test file")

    monkeypatch.setattr(worker, "ask", forbidden_ask)
    selected = worker.choose_file(
        FakeClient([]),
        "通常の実装を修正してください",
        ["tests/test_management_router.py", "uhip/tests/test_schema_contracts.py"],
    )
    assert selected is None


def test_existing_test_guard_covers_root_and_nested_test_files(monkeypatch, tmp_path):
    cases = [
        ("test_app.py", "def test_contract():\n    assert value() == 1\n"),
        ("uhip/tests/test_schema_contracts.py", "def test_contract():\n    assert value() == 1\n"),
    ]
    for relative_path, original in cases:
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(original, encoding="utf-8")
        monkeypatch.setattr(worker, "ROOT", tmp_path)
        plan = {
            "no_change": False,
            "changes": [{
                "file": relative_path,
                "old": "assert value() == 1",
                "new": "assert value() == 2",
            }],
        }
        assert worker.validate_plan(plan, relative_path) == (
            False, "existing_test_modified"
        )



def test_apply_plan_rejects_empty_or_oversized_change_lists_without_writes(tmp_path, monkeypatch):
    target = tmp_path / "app.py"
    target.write_text("before\\n", encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    monkeypatch.setattr(worker, "MAX_FILES", 1)

    empty_ok, empty_detail, empty_touched = worker.apply_plan(
        {"no_change": False, "changes": []}
    )
    oversized_ok, oversized_detail, oversized_touched = worker.apply_plan(
        {
            "no_change": False,
            "changes": [
                {"file": "app.py", "old": "before", "new": "after"},
                {"file": "app.py", "old": "before", "new": "after-again"},
            ],
        }
    )

    assert (empty_ok, empty_detail, empty_touched) == (False, "invalid_change_count", [])
    assert (oversized_ok, oversized_detail, oversized_touched) == (
        False,
        "invalid_change_count",
        [],
    )
    assert target.read_text(encoding="utf-8") == "before\\n"


def test_apply_plan_preflights_all_anchors_before_any_write(tmp_path, monkeypatch):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("first-original\\n", encoding="utf-8")
    second.write_text("second-original\\n", encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    monkeypatch.setattr(worker, "MAX_FILES", 2)

    ok, detail, touched = worker.apply_plan(
        {
            "no_change": False,
            "changes": [
                {"file": "first.py", "old": "first-original", "new": "first-updated"},
                {"file": "second.py", "old": "missing-anchor", "new": "second-updated"},
            ],
        }
    )

    assert ok is False
    assert detail == "anchor_count_second.py:0"
    assert touched == []
    assert first.read_text(encoding="utf-8") == "first-original\\n"
    assert second.read_text(encoding="utf-8") == "second-original\\n"


def test_apply_plan_rejects_paths_outside_repository_root(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    ok, detail, touched = worker.apply_plan(
        {
            "no_change": False,
            "changes": [
                {"file": "../outside.py", "old": "before", "new": "after"}
            ],
        }
    )

    assert ok is False
    assert detail == "change_path_outside_root"
    assert touched == []



def test_apply_plan_rolls_back_target_when_write_fails_midway(tmp_path, monkeypatch):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("first-original\\n", encoding="utf-8")
    second.write_text("second-original\\n", encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    monkeypatch.setattr(worker, "MAX_FILES", 2)

    original_write_text = type(second).write_text
    failed_once = False

    def partial_then_fail(path, data, *args, **kwargs):
        nonlocal failed_once
        if path == second and data.startswith("second-updated") and not failed_once:
            failed_once = True
            original_write_text(path, data[:6], *args, **kwargs)
            raise OSError("simulated interrupted write")
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(type(second), "write_text", partial_then_fail)

    ok, detail, touched = worker.apply_plan(
        {
            "no_change": False,
            "changes": [
                {"file": "first.py", "old": "first-original", "new": "first-updated"},
                {"file": "second.py", "old": "second-original", "new": "second-updated"},
            ],
        }
    )

    assert ok is False
    assert detail == "apply_write_failed:OSError"
    assert touched == ["first.py"]
    assert first.read_text(encoding="utf-8") == "first-original\\n"
    assert second.read_text(encoding="utf-8") == "second-original\\n"

def test_refill_deterministic_test_insertions_preserve_suffix_and_converge(tmp_path, monkeypatch):
    from core.line_development_runtime import _deterministic_autonomous_test_plan

    target = "tests/test_autonomous_task_refill.py"
    target_dir = tmp_path / "tests"
    target_dir.mkdir()
    target_path = target_dir / "test_autonomous_task_refill.py"
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    eof_anchor = '    assert queue.read_text(encoding="utf-8") == queue_before'
    unrelated_tail = "\n\n\ndef test_unrelated_tail_must_survive():\n    assert True\n"
    initial = (
        "from pathlib import Path\nimport json\nimport pytest\n\n"
        "def test_existing_refill_behavior():\n"
        "    queue = Path('queue.json')\n"
        "    queue_before = queue.read_text(encoding='utf-8')\n"
        + eof_anchor + unrelated_tail
    )

    def apply_task(source, task_id):
        target_path.write_text(source, encoding="utf-8")
        plan, error = _deterministic_autonomous_test_plan(target, task_id)
        assert error is None
        assert plan is not None and plan.get("no_change") is not True
        change = plan["changes"][0]
        assert change["file"] == target
        assert source.count(change["old"]) == 1
        return source.replace(change["old"], change["new"], 1)

    cli_task = "task-refill-cli-test-20261102"
    read_json_task = "task-refill-read-json-test-20261102"
    cli_then_read = apply_task(apply_task(initial, cli_task), read_json_task)
    read_then_cli = apply_task(apply_task(initial, read_json_task), cli_task)

    assert cli_then_read == read_then_cli
    assert cli_then_read.count("def test_unrelated_tail_must_survive():") == 1
    assert cli_then_read.endswith("    assert True\n")

def test_refill_cli_insertion_fails_closed_on_intervening_test(tmp_path, monkeypatch):
    from core.line_development_runtime import _deterministic_autonomous_test_plan

    target = "tests/test_autonomous_task_refill.py"
    target_dir = tmp_path / "tests"
    target_dir.mkdir()
    target_path = target_dir / "test_autonomous_task_refill.py"
    anchor = '    assert queue.read_text(encoding="utf-8") == queue_before'
    intervening = "\n\n\ndef test_existing_intervening_test():\n    assert True\n\n\n"
    source = (
        "from pathlib import Path\n"
        "def test_existing():\n"
        "    queue = Path('queue.json')\n"
        "    queue_before = queue.read_text(encoding='utf-8')\n"
        + anchor + intervening
        + "def test_read_json_rejects_non_object_root(tmp_path: Path):\n    pass\n"
    )
    target_path.write_text(source, encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    plan, error = _deterministic_autonomous_test_plan(
        target, "task-refill-cli-test-20261102"
    )

    assert plan is None
    assert error == "deterministic_anchor_intervening_content:refill_cli"
    assert target_path.read_text(encoding="utf-8") == source



def test_safe_api_error_detail_reports_provider_metadata_without_secrets():
    class BadRequestError(Exception):
        status_code = 400
        code = "invalid_request"
        param = "max_tokens"
        message = "Invalid request for gsk-abcdefghijklmnopqrstuvwxyz1234567890"

    detail = worker._safe_api_error_detail(BadRequestError("do not expose this"))

    assert detail.startswith("status=400:code=invalid_request:param=max_tokens:")
    assert "Invalid request" in detail
    assert "gsk-" not in detail
    assert "abcdefghijklmnopqrstuvwxyz" not in detail




def test_safe_api_error_detail_exposes_only_known_provider_failure_metadata():
    class BadRequestError(Exception):
        status_code = 400
        body = {
            "error": {
                "code": "json_validate_failed",
                "failed_generation": (
                    "max completion tokens reached before generating a valid document"
                ),
            }
        }

    detail = worker._safe_api_error_detail(BadRequestError("provider rejected request"))

    assert "code=json_validate_failed" in detail
    assert (
        "failed_generation=max completion tokens reached before generating a valid document"
        in detail
    )



def test_safe_api_error_detail_includes_request_id_and_redacted_generation():
    class FakeResponse:
        headers = {
            "x-request-id": "req_abc123",
            "x-groq-region": "us-east-1",
            "authorization": "Bearer must-not-appear",
        }

    class BadRequestError(Exception):
        status_code = 400
        body = {
            "error": {
                "code": "json_validate_failed",
                "failed_generation": (
                    "invalid output gsk_abcdefghijklmnopqrstuvwxyz1234567890 "
                    "and api_key=supersecret"
                ),
            }
        }
        response = FakeResponse()

    detail = worker._safe_api_error_detail(BadRequestError("provider rejected request"))

    assert "request_id=req_abc123" in detail
    assert "region=us-east-1" in detail
    assert "failed_generation=invalid output [REDACTED] and api_key=[REDACTED]" in detail
    assert "supersecret" not in detail
    assert "must-not-appear" not in detail



def test_append_only_generation_failure_includes_safe_api_error_detail(monkeypatch, tmp_path):
    target = tmp_path / "tests" / "test_sample.py"
    target.parent.mkdir()
    target.write_text("def test_existing():\n    assert True\n", encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    class BadRequestError(Exception):
        status_code = 400
        code = "invalid_request"
        param = "max_tokens"
        message = "Requested token budget exceeds limit"

    def fail_ask(*args, **kwargs):
        raise BadRequestError("provider rejected request")

    monkeypatch.setattr(worker, "ask_text", fail_ask)
    plan, error = worker.build_append_only_test_plan(
        FakeClient([]), "Add one boundary regression", "tests/test_sample.py",
        target.read_text(encoding="utf-8"),
    )

    assert plan is None
    assert error.startswith(
        "append_only_test_generation_failed:BadRequestError:"
        "model=openai/gpt-oss-20b:groq_sdk="
    )
    assert "status=400:code=invalid_request:param=max_tokens:" in error
    assert "message=Requested token budget exceeds limit" in error
    assert target.read_text(encoding="utf-8") == "def test_existing():\n    assert True\n"

def test_catalog_exhaustion_fail_closed_task_has_deterministic_plan(monkeypatch, tmp_path):
    from core.line_development_runtime import _deterministic_autonomous_test_plan

    chosen = "tests/test_catalog_exhaustion_analyzer.py"
    target = tmp_path / chosen
    target.parent.mkdir(parents=True)
    anchor = "def test_public_function_discovery_skips_protocol_and_abstract_stubs():"
    target.write_text(anchor + "\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(worker, "ROOT", tmp_path)

    plan, error = _deterministic_autonomous_test_plan(
        chosen, "catalog-exhaustion-analyzer-main-fail-closed-20261105"
    )

    assert error is None
    assert plan is not None
    assert plan["source"] == "deterministic_autonomous_task"
    change = plan["changes"][0]
    assert change["file"] == chosen
    candidate = target.read_text(encoding="utf-8").replace(change["old"], change["new"], 1)
    compile(candidate, chosen, "exec")
    assert "test_main_fails_closed_on_malformed_recovery_state" in candidate

