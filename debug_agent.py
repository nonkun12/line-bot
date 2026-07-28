from github_client import get_github_file
from ai_client import generate_chat_completion


def run_debug_agent(error_text):

    try:
        code = get_github_file("app.py")

        prompt = f"""
あなたはAIデバッグエージェントです。

以下のエラーを解析してください。

エラー:
{error_text}

対象コード:
{code[:12000]}

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
                    "content": "あなたは優秀なPythonデバッグエンジニアです。"
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
