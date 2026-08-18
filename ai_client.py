from config import client, MODEL


def generate_chat_completion(*, messages, tools=None, tool_choice="auto", temperature=0.0, max_tokens=1024):
    kwargs = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    # Tool Callingを使う呼び出しでは、toolsをGroqへ明示的に渡す。
    # tool_choice=None はGroq側で「Toolを使わせない」と解釈され、
    # モデルがtool callを生成した場合に
    # "Tool choice is none, but model called a tool" (400) になるため、
    # Noneはautoへ正規化する。
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice if tool_choice is not None else "auto"

    return client.chat.completions.create(**kwargs)


def generate_secretary_report(prompt_body):
    return client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "あなたは優秀で親しみやすいAI秘書です。事実に基いて正確なレポートを作成します。"},
            {"role": "user", "content": prompt_body},
        ],
        temperature=0.2,
        max_tokens=700,
    )
