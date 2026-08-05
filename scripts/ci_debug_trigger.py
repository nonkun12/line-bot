
#!/usr/bin/env python3
"""
CI用 read-only pytest失敗ログ解析スクリプト (Phase A-2)

- 既存の debug_agent/ パッケージ (read_only設計) を再利用するだけで、
  新しい解析ロジックは追加しない。
- ファイル変更・git操作・外部API呼び出しは一切行わない。
- 標準出力に GitHub Actions Summary 向けの Markdown を出力する。

使い方:
    python3 scripts/ci_debug_trigger.py <pytest_output.log>
"""

import os
import re
import sys

# scripts/ 配下から実行されても debug_agent パッケージ (repoルート直下) を
# import できるように、リポジトリルートを sys.path へ追加する。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from debug_agent.collectors import collect_error  # noqa: E402
from debug_agent.analyzer import analyze_error  # noqa: E402
from debug_agent.safety import SafetyGuard  # noqa: E402

# Summary肥大化防止のため、解析には末尾のみを使用する
MAX_LOG_CHARS_FOR_ANALYSIS = 10000


def extract_failed_tests(log_text: str):
    """
    pytestの `FAILED xxx::yyy` 行を抽出する。

    新しい解析ロジックではなく、pytest標準出力フォーマットに対する
    単純な文字列抽出のみ。
    """
    return re.findall(r"^FAILED (\S+)", log_text, re.MULTILINE)


def build_summary(full_log: str) -> str:
    truncated = full_log[-MAX_LOG_CHARS_FOR_ANALYSIS:]

    failed_tests = extract_failed_tests(full_log)

    collected = collect_error(truncated)
    analysis = analyze_error(truncated)

    lines = []
    lines.append("## 🔍 AI Debug Agent - ログ解析結果 (Phase A-2: read-only)")
    lines.append("")
    lines.append(
        f"モード: `{SafetyGuard.MODE}` "
        "(ファイル変更・git commit・git push・deployは行いません)"
    )
    lines.append("")

    if failed_tests:
        lines.append("### ❌ 失敗したテスト")
        for name in failed_tests:
            lines.append(f"- `{name}`")
        lines.append("")

    lines.append("### 解析結果")
    lines.append(f"- 種類: `{analysis.get('type')}`")
    if analysis.get("location"):
        lines.append(f"- 発生場所: `{analysis.get('location')}`")
    lines.append(f"- 原因: {analysis.get('cause')}")
    lines.append(f"- 修正候補: {analysis.get('solution')}")
    lines.append(f"- 安全レベル: `{analysis.get('risk')}`")
    lines.append(
        f"- ログ長: {collected.get('length')} 文字 / "
        f"Traceback含む: {collected.get('has_traceback')}"
    )
    lines.append("")

    lines.append("<details>")
    lines.append("<summary>pytestログ全文を表示</summary>")
    lines.append("")
    lines.append("```")
    lines.append(full_log)
    lines.append("```")
    lines.append("</details>")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print(
            "usage: ci_debug_trigger.py <pytest_output.log>",
            file=sys.stderr,
        )
        sys.exit(1)

    log_path = sys.argv[1]

    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        full_log = f.read()

    print(build_summary(full_log))


if __name__ == "__main__":
    main()