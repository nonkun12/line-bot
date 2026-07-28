from ai_client import generate_chat_completion


def generate_patch(error_analysis, code):

    prompt = f"""
あなたはPython修正パッチ作成AIです。

以下のエラー解析結果と対象コードを確認してください。

## エラー解析
{error_analysis}

## 対象コード
{code[:12000]}


以下の形式で回答してください。

1. 修正理由

2. 修正対象箇所

3. 修正前コード

4. 修正後コード

5. unified diff形式


注意:
- 不要な変更は禁止
- 既存機能を壊さない
- 推測で大幅変更しない
"""


    response = generate_chat_completion(
        messages=[
            {
                "role": "system",
                "content": "あなたは安全なPythonコードレビュアーです。"
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.0,
        max_tokens=2048
    )


    return response.choices[0].message.content
