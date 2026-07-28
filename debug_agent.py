from github_client import get_github_file
from render_client import get_render_logs
from ai_client import generate_chat_completion
from code_analyzer import find_relevant_code


def run_debug_agent(error_text=""):

    try:
        # Render本番ログ取得
        logs = get_render_logs()

        # GitHubコード取得
        code = get_github_file("app.py")

        # エラー関連コード抽出
        relevant_code = find_relevant_code(code, logs)

        prompt = f"""
あなたはAIデバッグエージェントです。

本番環境(Render)で発生している問題を解析してください。
ログ内のERROR、Exception、HTTPエラーを最優先してください。推測ではなくログに存在する事実を使ってください。

Renderログ:
{logs[-8000:]}

ユーザー入力:
{error_text}

対象コード(app.py):
{relevant_code[:12000]}

回答形式:

1. 原因
2. 該当箇所
3. 修正方法
4. テスト方法
"""

        response = generate_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": "あなたは優秀なPythonデバッグエンジニアです。ログとコードから原因を特定してください。"
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.0,
            max_tokens=1024
        )

        return f"""
🔍 AI Debug Agent

{response.choices[0].message.content}
"""

    except Exception as e:
        return f"""
🔍 AI Debug Agent

解析エラー:

{e}
"""
