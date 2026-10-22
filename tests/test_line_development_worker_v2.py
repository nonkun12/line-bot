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

    def fake_run(cmd, timeout=900, input_text=None, env=None):
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

    def fake_run(cmd, timeout=900, input_text=None, env=None):
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



def test_auto_test_pytest_receives_only_allowlisted_environment(monkeypatch, tmp_path):
    secret_names = (
        "GROQ_API_KEY", "OPENAI_API_KEY", "GITHUB_TOKEN", "GH_TOKEN",
        "ACTIONS_RUNTIME_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
    )
    unsafe_runtime_names = ("HOME", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "TMPDIR")
    for name in (*secret_names, *unsafe_runtime_names):
        monkeypatch.setenv(name, "must-not-leak")
    monkeypatch.setenv("AUTONOMOUS_TASK_ID", "auto-test-tests-test_example-deadbeef1234")
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    observed = []

    diff = """--- a/tests/test_example.py
+++ b/tests/test_example.py
@@ -1,0 +2,2 @@
+def test_safe():
+    assert True
"""

    def fake_run(command, timeout=900, input_text=None, env=None):
        if command[:4] == ["git", "diff", "--no-ext-diff", "--unified=0"]:
            return subprocess.CompletedProcess(command, 0, stdout=diff, stderr="")
        if command[1:3] == ["-m", "py_compile"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:3] == ["/usr/bin/docker", "run", "--rm"]:
            assert command[3:5] == ["--network", "none"]
            assert "--read-only" in command
            assert command[command.index("--user") + 1] == "65534:65534"
            assert command[command.index("--volume") + 1].endswith(":/workspace:ro")
            assert "line-bot-auto-test-sandbox:latest" in command
            assert "python" in command and "-m" in command and "pytest" in command
            assert "no:cacheprovider" in command
            assert not any("TOKEN=" in item or "API_KEY=" in item for item in command)
            observed.append(dict(env or {}))
            return subprocess.CompletedProcess(command, 0, stdout="1 passed", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(worker, "run", fake_run)
    passed, output = worker.run_tests(["tests/test_example.py"], full_suite=False)

    assert passed, output
    assert len(observed) == 1
    child_env = observed[0]
    assert all(name not in child_env for name in (*secret_names, *unsafe_runtime_names))
    assert not any(name.startswith(("ACTIONS_", "GITHUB_", "GH_")) for name in child_env)
    assert child_env.get("PATH")
    assert child_env.get("PYTHONDONTWRITEBYTECODE") == "1"
    assert child_env.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") == "1"



def test_linux_auto_test_sandbox_is_read_only_and_networkless():
    if not sys.platform.startswith("linux"):
        return
    probe = (
        "import os, socket\n"
        "assert os.getuid() == 65534\n"
        "assert not os.access('/workspace', os.W_OK)\n"
        "open('/tmp/sandbox-probe', 'w').close()\n"
        "sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "sock.settimeout(1)\n"
        "try:\n"
        "    sock.connect(('1.1.1.1', 80))\n"
        "except OSError:\n"
        "    print('sandbox_ok')\n"
        "else:\n"
        "    raise SystemExit('network reachable')\n"
    )
    result = subprocess.run(
        [
            "/usr/bin/docker", "run", "--rm", "--pull=missing",
            "--network", "none",
            "--read-only",
            "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=64m,mode=1777",
            "--user", "65534:65534",
            "--workdir", "/workspace",
            "--volume", f"{worker.ROOT}:/workspace:ro",
            "--env", "HOME=/tmp",
            "--env", "PATH=/usr/local/bin:/usr/bin:/bin",
            "python:3.13-slim",
            "python", "-c", probe,
        ],
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        "Docker sandbox unavailable or isolation failed; generated test execution "
        "must fail closed: " + result.stderr[-1500:]
    )
    assert "sandbox_ok" in result.stdout
