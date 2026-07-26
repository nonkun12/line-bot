import re
import sys

from mcp_client import call_mcp_tool as _mcp_client_call_mcp_tool, parse_mcp_json_list


def _resolve_call_mcp_tool():
    app_module = sys.modules.get("app")
    patched = getattr(app_module, "call_mcp_tool", None) if app_module else None
    if callable(patched):
        return patched
    return _mcp_client_call_mcp_tool


# Groq(OpenAI互換)のfunction calling形式でMCPツールを公開する。
# ユーザーごとの記憶を分離するため、モデルには生の key/value だけを
# 触らせ、実際にMCPへ渡す際はサーバー側でuser_idを前置して名前空間を分ける。
# =========================
# 「」内の文字列を抽出するヘルパー
# =========================
# set_reminder / save_memory 等でユーザーが「」で明示的に指定した文言は、
# AIに言い換えさせず、原文からそのまま抜き出して使う。
# (AIが1回目のツール呼び出し判断時にtemperature=0でも稀に数文字だけ
#  言い換えてしまう(例: 「文字化けテスト」→「文字化ケトスト」)ことがあるため、
#  正確性が必要な箇所は原文優先にする)
def extract_quoted_text(original_message):
    print(f"[LOG] extract_quoted_text called")
    # 「」(一重)と『』(二重)の両方に対応する。
    # ユーザーが「私の名前は『のんくん』です」のように、文中の引用は『』、
    # 全体の括りは「」を使うケース(逆のケースも)があるため、両方拾う。
    matches = re.findall(r"[「『](.+?)[」』]", original_message)
    return matches[-1] if matches else None


# =========================
# 名前に関するkeyの統一
# =========================
# AIにkey名を自由に選ばせると、「name」「名前」「username」のように
# 保存時と取得時でkeyがブレて、get_memoryで見つからなくなることがある
# (「前に覚えた名前を忘れる」症状の主イン)。
# ユーザーの原文が明らかに名乗り(「〜という名前です」等)を意味している場合は、
# AIが選んだkeyを無視して "name" に強制的に統一する。
NAME_INTENT_PATTERN = re.compile(
    r"(名前は|名前を覚え|名前を教え|って呼んで|と呼んで|といいます|って言います)"
)


def normalize_memory_key(key, original_message):
    print(f"[LOG] normalize_memory_key called")
    if NAME_INTENT_PATTERN.search(original_message or ""):
        return "name"
    return key


# =========================
# remind_atのタイムゾーン補正
# =========================
# システムプロンプトでモデルに「+09:00付きのISO 8601で出力する」よう指示しているが、
# Groq/Llama系モデルは稀にタイムゾーン部分を省略して出力することがある
# (例: "2026-07-12T21:19:00" のようにオフセットなし)。
# JS(MCPサーバー側)のnew Date()はオフセットなしの文字列をUTCとして解釈するため、
# 「日本時間のつもりだった時刻」が実際には9時間ズレて登録されてしまう。
# これを防ぐため、タイムゾーン表記(Z または +HH:MM/-HH:MM)が末尾になければ、
# ここで明示的に +09:00 を補う。
TZ_SUFFIX_RE = re.compile(r"(Z|[+-]\d{2}:\d{2})$")


def ensure_jst_offset(remind_at):
    print(f"[LOG] ensure_jst_offset called")
    if not remind_at:
        return remind_at
    # モデルはJSTのつもりで時刻を生成しているが、稀に Z(UTC扱い)や
    # 誤ったオフセットを付けてしまうことがある(例: 21:19+JSTのつもりが21:19Zになる)。
    # このBotはJST運用のみを想定しているため、モデルが何を付けてきたかに関わらず、
    # 末尾のタイムゾーン表記を一旦取り除き、常に +09:00 を明示的に付け直す。
    stripped = TZ_SUFFIX_RE.sub("", remind_at)
    return stripped + "+09:00"


MCP_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "ユーザーに関する情報をkey/valueの形で記憶として保存する",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "記憶の項目名(例: name, hobby)"},
                    "value": {"type": "string", "description": "記憶する内容"}
                },
                "required": ["key", "value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_note",
            "description": "ユーザーのメモを保存する",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "メモタイトル"
                    },
                    "body": {
                        "type": "string",
                        "description": "メモ内容"
                    }
                },
                "required": ["title", "body"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_all_memory",
            "description": "ユーザーの全ての記憶を取得する",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": "ユーザーが過去に保存したメモを検索する専用ツール。この用途では必ずこのツールを使うこと。外部検索(brave_search等)は使用しない。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "検索する文字"
                    }
                },
                "required": ["keyword"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": (
                "指定した日時にユーザーへリマインドメッセージを送るよう予約する。"
                "「n分後」「n時間後」「明日の朝9時」のような相対/絶対どちらの表現でも、"
                "現在時刻を基準に具体的なISO 8601日時に変換してから呼び出すこと。"
                "「毎日」「毎朝」のように繰り返しを希望された場合は repeat='daily' を指定すること。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "remind_at": {
                        "type": "string",
                        "description": "ISO 8601形式の日時(タイムゾーン付き推奨、例: 2026-07-12T15:00:00+09:00)。repeat='daily'の場合は1回目に送る日時。"
                    },
                    "message": {
                        "type": "string",
                        "description": "リマインド時に送る内容"
                    },
                    "repeat": {
                        "type": "string",
                        "enum": ["none", "daily"],
                        "description": "繰り返しの種類。「毎日」「毎朝」等と言われた場合は'daily'、単発なら'none'(省略可、省略時はnone)。"
                    }
                },
                "required": ["remind_at", "message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_reminders",
            "description": (
                "登録済みで、まだ送信されていないリマインダーの一覧を取得する。"
                "「今何が入ってる?」「予定確認して」「リマインダー一覧」のように、"
                "ユーザーが登録済みの中身を具体的に確認したい場合にのみ使う。"
                "「どんなセットがある?」「セットって何?」のように、"
                "リマインダー機能そのものについて聞いている(まだ何も登録していない・"
                "雑談として聞いている)場合はこのツールを使わず、通常の会話で答えること。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "このツールを呼ぶ理由(任意、省略可。指定されなくてもよい)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_reminder",
            "description": (
                "指定したidのリマインダーをキャンセルする。"
                "idはlist_remindersで確認したものを使う。"
                "ユーザーが「さっきのキャンセルして」ように言った場合、"
                "まずlist_remindersでidを確認してから呼び出すこと。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "キャンセルしたいリマインダーのid"
                    }
                },
                "required": ["id"]
            }
        }
    }
]

# 記憶するvalueの整形
MEMORY_VALUE_EXTRACT_PATTERNS = {
    "favorite_food": re.compile(r"(?:私は)?好きな食べ物は(.+?)(?:です|だ)?[。.!！]*$"),
    "favorite_drink": re.compile(r"(?:私は)?好きな飲み物は(.+?)(?:です|だ)?[。.!！]*$"),
    "name": re.compile(r"(?:私の)?名前は(.+?)(?:です|だ)?[。.!！]*$"),
}


def clean_memory_value(key, value):
    print(f"[LOG] clean_memory_value called")
    pattern = MEMORY_VALUE_EXTRACT_PATTERNS.get(key)

    if not pattern:
        return value

    match = pattern.search(value or "")

    if match:
        return match.group(1).strip()

    return value


def dispatch_tool_call(user_id, name, arguments, original_message=""):
    print(f"[LOG] dispatch_tool_call called: name={name}")
    """
    LINEのuser_idはGroq(LLM)には見せず、ここでMCPツールの正式パラメータとして注入する。
    以前はkeyに"{user_id}:"を前置する自前ルールで分離していたが、
    MCPサーバー側がuser_idを必須パラメータとして受け取るようになったため、
    そのまま渡すだけでよくなった。
    """
    call_mcp_tool_fn = _resolve_call_mcp_tool()

    if name == "save_note":
        return call_mcp_tool_fn(
            "save_note",
            {
                "user_id": user_id,
                "title": arguments.get("title", "無題"),
                "body": arguments.get("body", "")
            }
        )
    if name == "save_memory":
        # ユーザーの質問文（「〜は？」で終わる）である場合は保存をスキップする
        msg_stripped = (original_message or "").strip()
        if msg_stripped.endswith(("は？", "は?")):
            print("SAVE_MEMORY SKIPPED: message ends with 'は？' or 'は?'")
            return "ユーザーの質問文であるため、記憶への保存はスキップされました。"

        # 「覚えて」「覚えておいて」などの命令文を除去し、arguments["value"]へ戻す
        val = arguments.get("value", "")
        for word in ["記憶してください", "覚えておいて", "記憶して", "覚えて"]:
            val = val.replace(word, "")
        arguments["value"] = val.strip()

        # arguments["key"] が "memory" の場合、内容から適切に分類
        if arguments.get("key") == "memory":
            val_content = arguments.get("value", "")
            if "好きな食べ物" in val_content:
                arguments["key"] = "favorite_food"
            elif "好きな飲み物" in val_content:
                arguments["key"] = "favorite_drink"
            elif "私の名前" in val_content or "名前は" in val_content:
                arguments["key"] = "name"
            elif "Python" in val_content:
                arguments["key"] = "study_plan"

        # set_reminderと同様、AIが生成したvalueは稀に数文字言い換わることがあるため、
        # ユーザーの原文に「」/『』で明示された文言があれば、そちらを優先して使う。
        # (例: 「私の名前は『のんくん』です、覚えておいて」)
        quoted = extract_quoted_text(original_message)
        final_value = quoted if quoted else arguments.get("value", "")
        final_key = normalize_memory_key(arguments.get("key", ""), original_message)
        final_value = clean_memory_value(final_key, final_value)

        return call_mcp_tool_fn("save_memory", {
            "user_id": user_id,
            "key": final_key,
            "value": final_value
        })

    if name == "get_memory":
        final_key = normalize_memory_key(arguments.get("key", ""), original_message)
        return call_mcp_tool_fn("get_memory", {
            "user_id": user_id,
            "key": final_key
        })

    if name == "get_all_memory":
        return call_mcp_tool_fn("get_all_memory", {
            "user_id": user_id
        })

    if name == "search_notes":
        keyword = arguments.get("keyword", "")

        # 検索質問の余計な表現を除去
        for word in [
            "のメモ",
            "メモある",
            "メモありますか",
            "ありますか",
            "ある？",
            "ある?"
        ]:
            keyword = keyword.replace(word, "")

        keyword = keyword.strip()

        print("SEARCH KEYWORD CLEANED:", keyword)

        return call_mcp_tool_fn("search_notes", {
            "user_id": user_id,
            "keyword": keyword
        })

    if name == "set_reminder":
        quoted = extract_quoted_text(original_message)

        if quoted:
            final_message = quoted
        else:
            final_message = re.sub(
                r"^(.*?)(後に|後で|あとで|に|まで).*?(教えて|知らせて|リマインドして|通知して|言って|連絡して)",
                "",
                original_message
            ).strip()

        if not final_message:
            final_message = arguments.get("message", "")

        return call_mcp_tool_fn("set_reminder", {
            "user_id": user_id,
            "remind_at": ensure_jst_offset(arguments.get("remind_at", "")),
            "message": final_message,
            "repeat": arguments.get("repeat", "none")
        })

    if name == "list_reminders":
        return call_mcp_tool_fn("list_reminders", {
            "user_id": user_id
        })

    if name == "cancel_reminder":
        reminder_id = arguments.get("id")

        if not reminder_id:
            reminders = call_mcp_tool_fn(
                "list_reminders",
                {
                    "user_id": user_id
                }
            )

            reminder_list = parse_mcp_json_list(reminders)

            if reminder_list:
                reminder_id = reminder_list[-1].get("id")

        if not reminder_id:
            return "キャンセルできるリマインダーがありません。"

        return call_mcp_tool_fn(
            "cancel_reminder",
            {
                "user_id": user_id,
                "id": reminder_id
            }
        )

    if name == "delete_memory":
        final_key = normalize_memory_key(
            arguments.get("key", ""),
            original_message
        )

        return call_mcp_tool_fn("delete_memory", {
            "user_id": user_id,
            "key": final_key
        })

    return f"不明なツールです: {name}"
