import logging

from config import client, MODEL

logger = logging.getLogger(__name__)


def _chat_completion_with_rate_limit_logging(**kwargs):
    try:
        return client.chat.completions.create(**kwargs)
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)

        if status_code is not None:
            logger.error("GROQ ERROR status_code=%s error_type=%s error=%s", status_code, type(exc).__name__, exc)
        if headers is not None:
            for name in (
                "retry-after",
                "x-ratelimit-remaining-requests",
                "x-ratelimit-remaining-tokens",
                "x-ratelimit-reset-requests",
                "x-ratelimit-reset-tokens",
            ):
                if name in headers:
                    logger.error("GROQ HEADER %s=%s", name, headers[name])

        raise


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

    return _chat_completion_with_rate_limit_logging(**kwargs)


def generate_secretary_report(prompt_body):
    return _chat_completion_with_rate_limit_logging(
        model=MODEL,
        messages=[
            {"role": "system", "content": "あなたは優秀で親しみやすいAI秘書です。事実に基いて正確なレポートを作成します。"},
            {"role": "user", "content": prompt_body},
        ],
        temperature=0.2,
        max_tokens=700,
    )
