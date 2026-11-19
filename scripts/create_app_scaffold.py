"""Create a small, safe, self-contained starter app for explicit new-app requests.

This path creates files only under apps/generated/<slug>/ and never executes user
input. The initial scaffold is a functional browser-based task list that can be
extended by later guarded development passes.
"""
from __future__ import annotations

import argparse
import html
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEW_APP_PATTERN = re.compile(
    r"(?:新規|新しい|新規の).{0,20}(?:アプリ|webアプリ|システム|サービス)|"
    r"(?:アプリ|webアプリ|システム|サービス).{0,20}(?:作って|作成|開発|構築)|"
    r"\b(?:create|build|make|develop)\s+(?:a\s+)?(?:new\s+)?(?:web\s+)?app\b",
    re.IGNORECASE,
)
MAX_INSTRUCTION_LENGTH = 2000


def is_new_app_request(instruction: str) -> bool:
    """Classify only clear app-creation requests; maintenance stays on the normal path."""
    value = str(instruction or "").strip()
    if not value or len(value) > MAX_INSTRUCTION_LENGTH:
        return False
    return bool(NEW_APP_PATTERN.search(value))


def safe_slug(instruction: str, run_id: str = "local") -> str:
    """Derive a filesystem-safe ASCII slug without trusting user-supplied paths."""
    words = re.findall(r"[A-Za-z0-9]+", instruction.lower())
    slug = "-".join(words[:5]).strip("-")[:48]
    if not slug:
        run_token = re.sub(r"[^A-Za-z0-9-]", "", str(run_id))[:24] or "local"
        slug = f"app-{run_token.lower()}"
    return slug


def render_index(title: str) -> str:
    safe_title = html.escape(title.strip()[:80] or "新しいアプリ")
    # Keep the starter self-contained: no external scripts, remote assets, or APIs.
    return f'''<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="A self-contained app starter created by LINE AI Secretary.">
  <title>{safe_title}</title>
  <style>
    :root {{ color-scheme: light dark; font: 16px/1.5 system-ui, sans-serif; }}
    body {{ max-width: 42rem; margin: 3rem auto; padding: 0 1rem; }}
    h1 {{ overflow-wrap: anywhere; }}
    form {{ display: flex; gap: .5rem; }}
    input {{ flex: 1; min-width: 0; padding: .7rem; }}
    button {{ padding: .65rem .9rem; cursor: pointer; }}
    li {{ display: flex; gap: .6rem; align-items: center; margin: .6rem 0; }}
    li span {{ flex: 1; overflow-wrap: anywhere; }}
    li.done span {{ text-decoration: line-through; opacity: .65; }}
  </style>
</head>
<body>
  <main>
    <h1>{safe_title}</h1>
    <p>ローカル保存に対応したアプリの初期版です。追加・完了・削除を試せます。</p>
    <form id="task-form">
      <label for="task-input" hidden>タスク</label>
      <input id="task-input" maxlength="200" placeholder="タスクを入力" required>
      <button type="submit">追加</button>
    </form>
    <ul id="tasks" aria-live="polite"></ul>
  </main>
  <script>
    (() => {{
      const key = "line-ai-secretary-app-tasks-v1";
      const form = document.querySelector("#task-form");
      const input = document.querySelector("#task-input");
      const list = document.querySelector("#tasks");
      let tasks = [];
      try {{
        const stored = JSON.parse(localStorage.getItem(key) || "[]");
        if (Array.isArray(stored)) tasks = stored.filter(
          item => item && typeof item.text === "string" &&
          typeof item.done === "boolean" && item.text.length <= 200
        );
      }} catch (_) {{ tasks = []; }}
      const save = () => {{
        try {{ localStorage.setItem(key, JSON.stringify(tasks)); }}
        catch (_) {{ /* The app remains usable if browser storage is unavailable. */ }}
      }};
      const render = () => {{
        list.replaceChildren();
        tasks.forEach((task, index) => {{
          const item = document.createElement("li");
          if (task.done) item.classList.add("done");
          const toggle = document.createElement("input");
          toggle.type = "checkbox";
          toggle.checked = task.done;
          toggle.setAttribute("aria-label", "完了状態を変更");
          toggle.addEventListener("change", () => {{
            tasks[index].done = toggle.checked; save(); render();
          }});
          const text = document.createElement("span");
          text.textContent = task.text;
          const remove = document.createElement("button");
          remove.type = "button"; remove.textContent = "削除";
          remove.addEventListener("click", () => {{
            tasks.splice(index, 1); save(); render();
          }});
          item.append(toggle, text, remove); list.append(item);
        }});
      }};
      form.addEventListener("submit", event => {{
        event.preventDefault();
        const value = input.value.trim();
        if (!value || value.length > 200) return;
        tasks.push({{ text: value, done: false }});
        input.value = ""; save(); render(); input.focus();
      }});
      render();
    }})();
  </script>
</body>
</html>
'''


def create_app(instruction: str, *, root: Path = ROOT, run_id: str = "local") -> list[Path]:
    """Create exactly two new files under the generated-app root, refusing overwrite."""
    instruction = str(instruction or "").strip()
    if not is_new_app_request(instruction):
        raise ValueError("instruction is not an explicit new-app request")
    if len(instruction) > MAX_INSTRUCTION_LENGTH:
        raise ValueError("instruction exceeds the configured limit")
    slug = safe_slug(instruction, run_id)
    root_resolved = root.resolve()
    allowed_root = (root / "apps" / "generated").resolve()
    base = (root / "apps" / "generated" / slug).resolve()
    if (
        not allowed_root.is_relative_to(root_resolved)
        or allowed_root == root_resolved
        or not base.is_relative_to(allowed_root)
        or base == allowed_root
    ):
        raise ValueError("generated app path is outside the allowed root")
    index_path = base / "index.html"
    readme_path = base / "README.md"
    if index_path.exists() or readme_path.exists() or base.exists():
        raise FileExistsError(f"generated app already exists: {slug}")
    base.mkdir(parents=True, exist_ok=False)
    title = instruction[:80]
    index_path.write_text(render_index(title), encoding="utf-8")
    readme_path.write_text(
        f"# {title.replace(chr(10), ' ').replace(chr(13), ' ')}\n\n"
        "Starter generated by LINE AI Secretary. The current scaffold is a self-contained "
        "browser task list using localStorage. Review and extend it through the guarded "
        "development workflow before production use.\n",
        encoding="utf-8",
    )
    return [index_path, readme_path]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instruction", required=True)
    parser.add_argument("--run-id", default="local")
    parser.add_argument("--branch", default="")
    args = parser.parse_args()
    try:
        paths = create_app(args.instruction, run_id=args.run_id)
    except (ValueError, FileExistsError, OSError) as exc:
        print(f"APP_SCAFFOLD=BLOCKED reason={type(exc).__name__}: {exc}")
        return 1
    for path in paths:
        print(f"APP_SCAFFOLD=CREATED path={path.relative_to(ROOT)}")
    if args.branch:
        branch = args.branch
        if not re.fullmatch(r"line-dev/[A-Za-z0-9._-]{1,100}", branch):
            print("APP_SCAFFOLD=BLOCKED reason=invalid_branch")
            return 1
        def run(command: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=60)
        if run(["git", "checkout", "-B", branch]).returncode:
            print("APP_SCAFFOLD=FAIL reason=branch_checkout")
            return 1
        added = run(["git", "add", "--", *(str(path.relative_to(ROOT)) for path in paths)])
        if added.returncode:
            print(added.stderr[-2000:]); return 1
        committed = run(["git", "-c", "user.name=github-actions[bot]", "-c",
                         "user.email=41898282+users.noreply.github.com", "commit", "-m",
                         "feat: scaffold new app from LINE request"])
        if committed.returncode:
            print(committed.stderr[-2000:]); return 1
        pushed = run(["git", "push", "origin", branch])
        if pushed.returncode:
            print(pushed.stderr[-2000:]); return 1
        print(f"APP_SCAFFOLD=PUSHED branch={branch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
