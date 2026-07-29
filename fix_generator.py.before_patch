import os
from datetime import datetime


def generate_fixed_file(original_code, fixed_code, filename="app.py.fixed"):

    try:

        with open(filename, "w", encoding="utf-8") as f:
            f.write(fixed_code)

        return f"""
🛠️ Fix Generator

修正版ファイル作成完了

ファイル:
{filename}

サイズ:
{len(fixed_code)} 文字

作成時刻:
{datetime.now()}
"""

    except Exception as e:

        return f"""
🛠️ Fix Generator

生成エラー:

{e}
"""


def create_backup(filename):

    if not os.path.exists(filename):
        return "バックアップ対象なし"

    backup = filename + ".backup"

    with open(filename, "r", encoding="utf-8") as src:
        data = src.read()

    with open(backup, "w", encoding="utf-8") as dst:
        dst.write(data)

    return f"バックアップ作成: {backup}"
