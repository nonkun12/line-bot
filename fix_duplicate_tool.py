from pathlib import Path

p = Path("app.py")
s = p.read_text()

old = """        tool_results_by_name = {}
        for tc in choice.tool_calls:
            tc_name = tc.function.name
"""

new = """        tool_results_by_name = {}
        executed_side_effect_tools = set()

        for tc in choice.tool_calls:
            tc_name = tc.function.name

            if tc_name in {
                "set_reminder",
                "cancel_reminder",
                "save_memory"
            }:
                if tc_name in executed_side_effect_tools:
                    print(f"[SKIP DUPLICATE TOOL] {tc_name}")
                    continue

                executed_side_effect_tools.add(tc_name)
"""

if old not in s:
    print("対象箇所が見つかりません")
    exit(1)

s = s.replace(old, new, 1)

p.write_text(s)

print("修正完了")
