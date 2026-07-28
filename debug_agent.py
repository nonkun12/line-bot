from github_client import get_github_file


def run_debug_agent(error_text):

    try:
        code = get_github_file("app.py")

        return f"""
🔍 AI Debug Agent

エラー:
{error_text}


GitHubからapp.py取得成功

コードサイズ:
{len(code)} 文字

次の段階:
AI解析を追加します
"""

    except Exception as e:

        return f"""
🔍 AI Debug Agent

GitHub取得エラー:

{e}
"""
