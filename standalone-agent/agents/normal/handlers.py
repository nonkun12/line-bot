"""
Normal Agent handlers

旧 generate_reply() の末尾に存在していた、GitHub/Debug/Memory/Notes
のいずれにも該当しない通常メッセージに対する Groq 応答処理(function
calling ループ)を LangGraph Node として移植したもの。

既存の Groq API 呼び出し仕様(システムプロンプト・ツールスキーマ・
tool_calls 処理・エラーハンドリング)は変更せず、そのまま踏襲する。
"""

import json
import random
import re
from datetime import datetime, timezone, timedelta

from ai_client import generate_chat_completion
from bot_tools import MCP_TOOLS_SCHEMA, dispatch_tool_call, ensure_jst_offset
from db import load_history, save_message


_PERSONALITIES = [
    "あなたは優しくフレンドリーなAIです。",
    "あなたは少し冗談を言う親しみやすいAIです。",
    "あなたは落ち着いた相談相手のようなAIです。",
]

_INLINE_FUNCTION_CALL_RE = re.compile(
    r"<function=([a-zA-Z0-9_]+)\s*(\{.*\})?\s*(?:/?>|</function>)",
    re.DOTALL,
)

_SANITIZE_FUNCTION_CALL_RE = re.compile(
    r"<function=[a-zA-Z0-9_]+.*?(?:/>|</function>)",
    re.DOTALL,
)

_SAFE_INLINE_TOOLS = {
    "list_reminders",
    "get_memory",
    "save_memory",
    "search_notes",
    "get_today_schedule",
}

_SAFE_FALLBACK_TOOLS = {"list_reminders", "get_memory"}

_RATE_LIMIT_REPLY = (
    "ごめんなさい、今日利用できるAIの上限に達してしまいました🙏\n"
    "しばらく時間をおいてから、もう一度話しかけてみてください。"
)
_AUTH_ERROR_REPLY = "AIサービスへの接続設定に問題があるようです。少し時間を置いてもう一度お試しください。"
_SERVER_ERROR_REPLY = "AIサービス側で一時的な不具合が起きているようです。少ししてからもう一度お試しください。"
_TIMEOUT_REPLY = "応答に時間がかかりすぎたため、一度中断しました。もう一度話しかけてみてください。"
_GENERIC_ERROR_REPLY = "エラーが発生してしまいました。もう一度試してみてください🙏"
_SANITIZED_REPLY = "うまく処理できませんでした。もう一度お試しください🙏"


def _error_status_reply(e):
    status_code = getattr(e, "status_code", None)

    if status_code == 429 or "429" in str(e):
        return _RATE_LIMIT_REPLY
    if status_code in (401, 403):
        return _AUTH_ERROR_REPLY
    if status_code is not None and status_code >= 500:
        return _SERVER_ERROR_REPLY
    if "timeout" in str(e).lower() or "timed out" in str(e).lower():
        return _TIMEOUT_REPLY
    return None


def handle_normal_message(message, user_id, call_mcp_tool):
    """
    GitHub / Debug / Memory / Notes のいずれにも該当しない通常メッセージに
    対する、Groq(function calling)ベースのAI応答を生成する。
    """

    print("===== NORMAL AGENT START =====")
    print("USER:", user_id)
    print("MESSAGE:", message)

    now_jst = datetime.now(timezone(timedelta(hours=9)))
    now_str = now_jst.strftime("%Y-%m-%dT%H:%M:%S+09:00")

    # 名前などの既知情報は、AIのtool呼び出し判断に任せず毎回直接取得して
    # システムプロンプトへ埋め込む(会話履歴に残っていなくても思い出せるようにするため)。
    try:
        stored_memory = call_mcp_tool(
            "get_all_memory",
            {"user_id": user_id},
        )
    except Exception as e:
        print("GET ALL MEMORY ERROR:", e)
        stored_memory = ""

    known_facts_block = stored_memory if stored_memory else "(まだ何も記憶していません)"

    system_prompt = f"""
{random.choice(_PERSONALITIES)}

現在の日時: {now_str} (JST)

【このユーザーについて既に記憶している情報】
{known_facts_block}

上記に情報がある場合は、それが必ず正しい最新の情報です。
会話履歴に見当たらなくても、上記の記憶している情報を優先して答えてください。
「覚えていません」「わかりません」と答える前に、必ず上記を確認してください。

記憶情報は既に提供されています。
get_memoryツールは使用しないでください。
ユーザーの発言が質問形式（「〜は？」で終わるもの）の場合、save_memory ツールは使用しないでください。

外部検索ツール(brave_searchなど)は存在しません。検索が必要な場合でも、利用可能なツール一覧にあるものだけを使用してください。
メモ検索は必ず search_notes ツールを使用してください。
ユーザーが過去のメモ・記録・予定・作業内容について確認している場合は、
記憶情報ではなく必ず search_notes ツールを使用してください。
例:
「牛乳を買う予定あった？」
「LINE Bot開発のメモある？」
「前に書いた内容は？」
「〇〇についてメモ残ってる？」
これらはnotes検索であり、get_all_memoryやsave_memoryは使用しません。

ユーザーについて新しく覚えておくべきことがあれば save_memory ツールで保存し、
上記に載っていないその他の情報を思い出す必要があれば get_all_memory ツールで確認してください。
ツールのkeyはユーザーごとに自動で区別されるので、あなたはkey名(name, hobbyなど)だけ気にしてください。
名前を保存・取得する際は、必ずkey="name"を使ってください。

重要:
「覚えて」「記憶して」という言葉が含まれていても、
「10分後」「30分後」「○時」「明日」「毎日」のような時間指定やリマインダーの意図が含まれている場合は、
save_memoryではなく 必ず set_reminder ツールを使用してください。
"""

    history = load_history(user_id)[-6:]
    messages = [{"role": "system", "content": system_prompt}]

    for role, content in history:
        if role == "user" and content == message:
            continue
        messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": message})

    sanitized_override_reply = None
    choice = None
    forced_tool_call = None
    forced_tool_args = {}

    try:
        response = generate_chat_completion(
            messages=messages,
            tools=MCP_TOOLS_SCHEMA,
            tool_choice=None,
            temperature=0.0,
            max_tokens=1024,
        )

        choice = response.choices[0].message

        tool_calls_happened = False
        try:
            if getattr(choice, "tool_calls", None):
                tool_calls_happened = True
        except Exception as e:
            print("CHECK TOOL CALLS ERROR:", e)

        if not tool_calls_happened:
            # 稀にcontent内へ壊れたfunction-call文字列が混入することがあるため、
            # その場合は同じforced_tool_call経路へ合流させる。
            inline_content = choice.content or ""
            inline_match = _INLINE_FUNCTION_CALL_RE.search(inline_content)

            if inline_match:
                print("INLINE FUNCTION-CALL STRING DETECTED IN CONTENT:", repr(inline_content))
                inline_name = inline_match.group(1)
                inline_args = {}
                if inline_match.group(2):
                    try:
                        inline_args = json.loads(inline_match.group(2))
                    except Exception as args_err:
                        print("INLINE FUNCTION-CALL ARGS PARSE ERROR:", args_err)
                        inline_args = {}

                if inline_name in _SAFE_INLINE_TOOLS:
                    forced_tool_call = inline_name
                    forced_tool_args = inline_args

                elif inline_name == "set_reminder":
                    reminder_message = inline_args.get("message")
                    reminder_remind_at = inline_args.get("remind_at")

                    validated_args = None
                    if reminder_message and reminder_remind_at:
                        try:
                            normalized_remind_at = ensure_jst_offset(reminder_remind_at)
                            datetime.fromisoformat(normalized_remind_at)
                            validated_args = dict(inline_args)
                            validated_args["remind_at"] = normalized_remind_at
                        except Exception as validate_err:
                            print("INLINE SET_REMINDER VALIDATION ERROR:", validate_err)
                            validated_args = None

                    if validated_args is not None:
                        forced_tool_call = "set_reminder"
                        forced_tool_args = validated_args
                    else:
                        print("INLINE SET_REMINDER REJECTED (invalid args):", repr(inline_args))
                        sanitized_override_reply = _SANITIZED_REPLY

                else:
                    sanitized_override_reply = _SANITIZED_REPLY

    except Exception as e:
        print("TOOL CALL ERROR CHECK, ATTEMPTING FALLBACK:", e)

        status_reply = _error_status_reply(e)
        if status_reply is not None:
            print("===== NORMAL AGENT END (STATUS ERROR, NO TOOL CALL) =====")
            return status_reply

        failed_name = None
        failed_args = {}
        try:
            body = getattr(e, "body", None) or {}
            failed_gen = body.get("error", {}).get("failed_generation", "")
            m = _INLINE_FUNCTION_CALL_RE.search(failed_gen)
            if m:
                failed_name = m.group(1)
                if m.group(2):
                    try:
                        failed_args = json.loads(m.group(2))
                    except Exception as args_err:
                        print("FAILED_GENERATION ARGS PARSE ERROR:", args_err)
                        failed_args = {}
        except Exception as parse_err:
            print("FAILED_GENERATION PARSE ERROR:", parse_err)

        if failed_name in _SAFE_FALLBACK_TOOLS:
            forced_tool_call = failed_name
            forced_tool_args = failed_args
            choice = None
        else:
            print("===== NORMAL AGENT END (UNRECOVERABLE FIRST-CALL ERROR) =====")
            return _GENERIC_ERROR_REPLY

    tool_calls_happened = bool(forced_tool_call) or bool(choice.tool_calls if choice else False)
    tool_results_by_name = {}

    if forced_tool_call:
        fallback_id = "fallback_call_1"
        messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": fallback_id,
                    "type": "function",
                    "function": {
                        "name": forced_tool_call,
                        "arguments": json.dumps(forced_tool_args, ensure_ascii=False),
                    },
                }
            ],
        })

        try:
            tool_result = dispatch_tool_call(user_id, forced_tool_call, forced_tool_args, original_message=message)
        except Exception as e:
            print("MCP TOOL CALL ERROR:", e)
            tool_result = f"ツール実行エラー: {e}"

        tool_results_by_name.setdefault(forced_tool_call, []).append(tool_result)

        messages.append({
            "role": "tool",
            "tool_call_id": fallback_id,
            "content": tool_result,
        })

    elif choice.tool_calls:
        messages.append({
            "role": "assistant",
            "content": choice.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in choice.tool_calls
            ],
        })

        executed_side_effect_tools = set()

        for tc in choice.tool_calls:
            tc_name = tc.function.name

            if tc_name in {"set_reminder", "cancel_reminder", "save_memory"}:
                if tc_name in executed_side_effect_tools:
                    print(f"[SKIP DUPLICATE TOOL] {tc_name}")
                    continue
                executed_side_effect_tools.add(tc_name)

            try:
                tc_args = json.loads(tc.function.arguments)
            except Exception as e:
                print("JSON PARSE ERROR FOR TOOL ARGS:", e)
                tc_args = {}

            try:
                tool_result = dispatch_tool_call(user_id, tc_name, tc_args, original_message=message)
            except Exception as e:
                print("MCP TOOL CALL ERROR:", e)
                tool_result = f"ツール実行エラー: {e}"

            tool_results_by_name.setdefault(tc_name, []).append(tool_result)

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tool_result,
            })

    try:
        if tool_calls_happened:
            is_note_search_call = any(
                name in tool_results_by_name
                for name in ["search_notes", "list_reminders", "get_today_schedule"]
            )

            if is_note_search_call:
                messages.append({
                    "role": "system",
                    "content": (
                        "上記はツールからの取得結果です。\n"
                        "この結果をもとに、ユーザーへわかりやすく自然な日本語で答えてください。\n"
                        "例:\n"
                        "tool結果が {\"title\": \"牛乳を買う\", \"body\": \"牛乳を買う\"} の場合\n"
                        "→「牛乳を買うというメモがあります」\n\n"
                        "tool結果が複数件の配列の場合は、内容をもとに箇条書きで自然に紹介してください。\n"
                        "tool結果が空、またはメモが見つからなかった場合は「メモは見つかりませんでした」のように伝えてください。"
                    ),
                })

            res2 = generate_chat_completion(
                messages=messages,
                temperature=0.85,
                max_tokens=1024,
            )
            reply = res2.choices[0].message.content
        else:
            reply = (
                sanitized_override_reply
                if sanitized_override_reply is not None
                else choice.content
            )

    except Exception as e:
        print("AI ERROR:", e)
        status_reply = _error_status_reply(e)
        reply = status_reply if status_reply is not None else _GENERIC_ERROR_REPLY

    # LINE送信直前の最終防波堤: function-call文字列の残存を検出したら定型文へ差し替える
    if reply and _SANITIZE_FUNCTION_CALL_RE.search(reply):
        print("SANITIZE: FUNCTION-CALL STRING FOUND IN FINAL REPLY, REPLACING:", repr(reply))
        reply = _SANITIZED_REPLY

    save_message(user_id, "user", message)
    save_message(user_id, "assistant", reply)

    print("===== NORMAL AGENT END =====")
    return reply
