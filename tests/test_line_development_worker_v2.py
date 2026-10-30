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
    assert detail == "anchor_count_app.py:2"
    assert touched == []
    assert len(anchor_calls) == worker.MAX_APPLY_REPAIR_ATTEMPTS
    assert size_calls == [1]
    assert plan == size_repaired_but_ambiguous
    assert target.read_text(encoding="utf-8") == original
