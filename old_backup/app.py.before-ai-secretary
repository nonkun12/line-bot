from flask import Flask, request, jsonify
from linebot.v3.webhook import WebhookHandler
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage
)
from groq import Groq
import os
import unicodedata
from dotenv import load_dotenv

load_dotenv()
import sqlite3
import json
import random
import threading
import httpx
import logging
logging.basicConfig(level=logging.DEBUG)
import re
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

# =========================
# ENV
# =========================
CHANNEL_ACCESS_TOKEN = os.environ["CHANNEL_ACCESS_TOKEN"]
CHANNEL_SECRET = os.environ["CHANNEL_SECRET"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

# MCPサーバー(Render上のmy-mcp-server)のURL。
# 例: https://my-mcp-server.onrender.com/mcp
MCP_SERVER_URL = os.environ["MCP_SERVER_URL"]

# MCPサーバー側のrequireApiKeyと照合される固定キー。
# my-mcp-server側の環境変数 MCP_API_KEY と同じ値をここに設定する。
MCP_API_KEY = os.environ["MCP_API_KEY"]

# MCPサーバー(スケジューラー)がリマインダー送信を依頼してくる際に
# このLINE Bot側の /internal/push エンドポイントを叩く。
# その時に付けてくるヘッダー "x-internal-key" と照合する値。
# my-mcp-server側の環境変数 INTERNAL_PUSH_KEY と同じ値をここに設定する。
INTERNAL_PUSH_KEY = os.environ["INTERNAL_PUSH_KEY"]

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
# timeoutを明示的に指定し、Groq側が詰まってもgunicorn workerごと
# ハングしないようにする(Renderがクラッシュと誤認して再起動する原因になっていた)
client = Groq(api_key=GROQ_API_KEY, timeout=15.0, max_retries=1)

MODEL = "llama-3.1-8b-instant"
DB = "chat.db"
print("===== APP VERSION CHECK =====")
print("search_notes enabled")
# =========================
# DB
# =========================
def get_conn():
    return sqlite3.connect(DB, check_same_thread=False)

def init_db():
    with get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            role TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        # 旧・自前memoryテーブルはもう使わない(MCPサーバー側のSQLiteに一元化)。
        # 既存データを残したい場合はこのテーブル定義とget_memory/update_memory関数を
        # 復活させて併用することも可能。

init_db()

# =========================
# 会話保存
# =========================
def save_message(user_id, role, content):
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO messages(user_id, role, content) VALUES (?, ?, ?)",
                (user_id, role, content)
            )
    except Exception as e:
        print("DB SAVE_MESSAGE ERROR:", e)

# =========================
# 履歴
# =========================
def load_history(user_id):
    try:
        with get_conn() as conn:
            rows = conn.execute("""
            SELECT role, content FROM messages
            WHERE user_id=?
            ORDER BY id DESC
            LIMIT 8
            """, (user_id,)).fetchall()
    except Exception as e:
        print("DB LOAD_HISTORY ERROR:", e)
        return []

    return list(reversed(rows))

# =========================================================
# MCPクライアント(StreamableHTTP / stateless)
# =========================================================
def call_mcp_tool(tool_name, arguments, timeout=3.0):
    """
    my-mcp-server の /mcp エンドポイントへ JSON-RPC で tools/call を送る。
    StreamableHTTPServerTransport はレスポンスを
    application/json または text/event-stream のどちらでも返し得るため両方に対応する。
    """
    
    print("MCP CALL:", tool_name, arguments)
    print("MCP URL:", MCP_SERVER_URL)
    
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        }
    }

    headers = {
        "Content-Type": "application/json",
        # stateless MCPサーバー側の要求に合わせて両方受け入れる旨を明示
        "Accept": "application/json, text/event-stream",
        # MCPサーバー側のrequireApiKeyミドルウェアで照合される
        "x-api-key": MCP_API_KEY,
        "Connection": "close"
    }

    import time
    print("BEFORE MCP REQUEST")
    print("TIMEOUT:", timeout)
    print("POST START TIME:", time.time())
    try:
        print("REQUEST START")
        print("MCP BEFORE REQUESTS POST")
        print("BEFORE POST CALL", time.time())
        res = httpx.post(
            MCP_SERVER_URL,
            json=payload,
            headers=headers,
            timeout=httpx.Timeout(10.0, connect=10.0),
            follow_redirects=False,
        )
        print("MCP AFTER REQUESTS POST")
        print("MCP RESPONSE STATUS:", res.status_code)
        print("MCP CONTENT TYPE:", res.headers.get("content-type"))
        print("RESPONSE OBJECT:", res)
    except Exception as e:
        import traceback
        print("EXCEPTION TYPE:", type(e))
        traceback.print_exc()
        raise
    print("REQUEST END")
    print("AFTER MCP REQUEST")
    print("POST END TIME:", time.time())

    print("MCP STATUS:", res.status_code)
    print("MCP HEADERS:", res.headers)

    res.raise_for_status()

    content_type = res.headers.get("content-type", "")

    if "text/event-stream" in content_type:
        # SSE形式: "data: {...}" 行からJSONを取り出す
        # これにより、サーバーから送られ続ける keep-alive 改行などの無限ストリームによるハングを防ぐ。
        body = None
        try:
            for line in res.iter_lines():
                if line:
                    decoded_line = line.decode("utf-8")
                    if decoded_line.startswith("data:"):
                        data_line = decoded_line[len("data:"):].strip()
                        body = json.loads(data_line)
                        break
        finally:
            res.close()

        if body is None:
            raise RuntimeError("MCP SSEレスポンスにdataが見つかりません")
    else:
        # JSON形式: 全体を読み込む
        try:
            body = res.json()
        finally:
            res.close()

    print("MCP PARSED BODY:", body)

    if "error" in body:
        raise RuntimeError(f"MCP error: {body['error']}")

    result = body.get("result", {})
    parts = result.get("content", [])
    texts = [p.get("text", "") for p in parts if p.get("type") == "text"]
    return "\n".join(texts) if texts else ""


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
# (「前に覚えた名前を忘れる」症状の主因)。
# ユーザーの原文が明らかに名乗り(「〜という名前です」等)を意味している場合は、
# AIが選んだkeyを無視して "name" に強制的に統一する。
NAME_INTENT_PATTERN = re.compile(
    r"(名前は|名前を覚え|名前を教え|って呼んで|と呼んで|といいます|って言います)"
)

def normalize_memory_key(key, original_message):
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
                # 注意: properties を空にすると、Groq上のLlama 3.1/3.3系モデルが
                # 正しいtool_call JSONの代わりに疑似タグ '<function=list_reminders />' を
                # そのままテキストとして生成し、tool_use_failed(400)になることがある
                # (Groq/Llama系の既知の傾向)。
                # これを避けるため、実際には使わない任意パラメータを1つ持たせておく。
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
                "ユーザーが「さっきのキャンセルして」のように言った場合、"
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
    pattern = MEMORY_VALUE_EXTRACT_PATTERNS.get(key)

    if not pattern:
        return value

    match = pattern.search(value or "")

    if match:
        return match.group(1).strip()

    return value

def dispatch_tool_call(user_id, name, arguments, original_message=""):


    """
    LINEのuser_idはGroq(LLM)には見せず、ここでMCPツールの正式パラメータとして注入する。
    以前はkeyに"{user_id}:"を前置する自前ルールで分離していたが、
    MCPサーバー側がuser_idを必須パラメータとして受け取るようになったため、
    そのまま渡すだけでよくなった。
    """
    if name == "save_note":
    
        return call_mcp_tool(
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

        return call_mcp_tool("save_memory", {
            "user_id": user_id,
            "key": final_key,
            "value": final_value
        })

    if name == "get_memory":
        final_key = normalize_memory_key(arguments.get("key", ""), original_message)
        return call_mcp_tool("get_memory", {
            "user_id": user_id,
            "key": final_key
        })

    if name == "get_all_memory":
        return call_mcp_tool("get_all_memory", {
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

        return call_mcp_tool("search_notes", {
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

        return call_mcp_tool("set_reminder", {
            "user_id": user_id,
            "remind_at": ensure_jst_offset(arguments.get("remind_at", "")),
            "message": final_message,
            "repeat": arguments.get("repeat", "none")
        })

    if name == "list_reminders":
        return call_mcp_tool("list_reminders", {
            "user_id": user_id
        })

    if name == "cancel_reminder":
        return call_mcp_tool("cancel_reminder", {
            "user_id": user_id,
            "id": arguments.get("id")
        })

    return f"不明なツールです: {name}"


# =========================
# 削除確認の保留状態
# =========================
# 「メモ全部削除」「記憶全部削除」等の後に送られる「はい」が、
# どちらの削除を指しているか区別するため、user_idごとに保留する。
_pending_delete_confirmation = {}
_pending_confirm_lock = threading.Lock()


# =========================
# AI本体(返信生成 + MCPツール呼び出しループ)
# =========================
def generate_reply(user_id, message):
    print("=== GENERATE_REPLY ===", repr(message))

    print("=== GENERATE_REPLY TEST ===", user_id, message)

    # =========================
    # 記憶系はAIを使わずMCP直行
    # =========================

    if "覚えて" in message and not any(
        p in message for p in ("教えて", "覚えていること", "覚えてること")
    ):
        if message.startswith("覚えて"):
            text = re.sub(r"^覚えて\s*[:：]?\s*", "", message)
        else:
            text = message.strip()

        key = "memory"
        value = text

        m = re.search(r"(?:私の)?名前は(.+?)(?:です|、|。|$)", message)

        if m:
            key = "name"
            value = m.group(1).strip()

        print("BEFORE SAVE_MEMORY MCP")
        return call_mcp_tool(
            "save_memory",
            {
                "user_id": user_id,
                "key": key,
                "value": value
            }
        )

    if "忘れて" in message:
        return call_mcp_tool(
            "delete_memory",
            {
                "user_id": user_id,
                "key": "name"
            }
        )

    if message in ["私の名前は？", "名前は？", "私の名前を教えて"]:
        name = call_mcp_tool(
            "get_memory",
            {
                "user_id": user_id,
                "key": "name"
            }
        )

        print("NAME FROM MCP:", repr(name))

        if name:
            return f"あなたの名前は {name} です。"

        return "名前はまだ記憶されていません。"

    # 名前確認はAI判断に任せず全記憶取得
    if "名前" in message:
        memories = call_mcp_tool(
            "get_all_memory",
            {
                "user_id": user_id
            }
        )

        print("GET_ALL_MEMORY RESULT:", repr(memories))

        try:
            if isinstance(memories, str):
                data = json.loads(memories)
            else:
                data = memories

            print("NAME DATA:", data)
            print("NAME DATA TYPE:", type(data))

            for item in data:
                if item.get("key") == "name":
                    return f"あなたの名前は {item.get('value')} です。"

        except Exception as e:
            print("NAME FORMAT ERROR:", e)

        return "名前はまだ記憶されていません。"


    # =========================
    # メモ系はAIを使わずMCP直行
    # =========================

    if message == "メモ一覧":
        return call_mcp_tool(
            "search_notes",
            {
                "user_id": user_id,
                "keyword": ""
            }
        )

    if message.startswith("メモ検索"):
        keyword = re.sub(r"^メモ検索\s*[:：]?\s*", "", message)
        if not keyword:
            return "検索キーワードを指定してください。\n例: メモ検索 テニス"
        return call_mcp_tool(
            "search_notes",
            {
                "user_id": user_id,
                "keyword": keyword
            }
        )

    if message.startswith("メモして"):
        body = re.sub(r"^メモして\s*[:：]?\s*", "", message)

        # 簡易カテゴリ判定
        if any(k in body.lower() for k in ["python", "program", "プログラム", "ai", "コード"]):
            category = "技術"
        elif any(k in body for k in ["勉強", "英語", "資格", "学習"]):
            category = "学習"
        elif any(k in body for k in ["予定", "予約", "会議", "行く"]):
            category = "予定"
        elif any(k in body for k in ["買う", "購入", "買い物"]):
            category = "生活"
        else:
            category = "一般"

        return call_mcp_tool(
            "save_note",
            {
                "user_id": user_id,
                "title": "LINEメモ",
                "body": body,
                "category": category
            }
        )


    # =========================
    # 予定・目標系は自動メモ保存（Groq不要）
    # =========================
    if (
        ("予定" in message or "したい" in message or "忘れないように" in message)
        and len(message) > 5
        and not any(q in message for q in [
            "ある？",
            "ありますか",
            "あるか",
            "あった？",
            "あったか",
            "確認",
            "教えて",
            "覚えて"
        ])
    ):
        return call_mcp_tool(
            "save_note",
            {
                "user_id": user_id,
                "title": "自動メモ",
                "body": message,
                "category": "一般"
            }
        )



    if message in [
        "記憶全部削除",
        "記憶をすべて削除",
        "記憶を全部削除",
        "全ての記憶を削除",
        "全部の記憶を削除"
    ]:
        with _pending_confirm_lock:
            _pending_delete_confirmation[user_id] = "delete_all_memory"
        return "記憶をすべて削除しますか？「はい」と送ってください"


    if message in [
        "メモ削除全部",
        "メモ全て削除",
        "メモを全部削除",
        "メモ全部消して",
        "メモ全部削除",
        "全メモ削除",
        "メモを全削除"
    ]:
        with _pending_confirm_lock:
            _pending_delete_confirmation[user_id] = "delete_all_notes"
        return "全メモを削除しますか？「はい」と送ってください"


    if message == "はい":
        with _pending_confirm_lock:
            pending = _pending_delete_confirmation.pop(user_id, None)

        if pending == "delete_all_notes":
            return call_mcp_tool(
                "delete_all_notes",
                {
                    "user_id": user_id
                }
            )

        if pending == "delete_all_memory":
            return call_mcp_tool(
                "delete_all_memory",
                {
                    "user_id": user_id
                }
            )

        # 確認待ちがなければ削除処理はせず、通常のAI応答へ流す(returnしない)


    # =========================
    # 自然文メモ削除
    # =========================
    m = re.search(r"(\d+)番.*メモ.*削除", message)

    if m:
        note_id = m.group(1)

        return call_mcp_tool(
            "delete_note",
            {
                "user_id": user_id,
                "id": note_id
            }
        )


    if message.startswith("メモ削除"):
        note_id = message.replace("メモ削除", "").strip()
        note_id = unicodedata.normalize("NFKC", note_id)

        if not note_id:
            return "削除するメモIDを指定してください。\n例: メモ削除25"

        print("DELETE DEBUG user_id=", user_id, "note_id=", note_id)

        return call_mcp_tool(
            "delete_note",
            {
                "user_id": user_id,
                "id": note_id
            }
        )

    if (
        "メモ" in message
        and (
            "探して" in message
            or "検索" in message
            or "見せて" in message
            or "私のメモ" in message
        )
    ):
        if "私のメモ" in message:
            keyword = ""
        else:
            keyword = (
                message
                .replace("LINE Botのメモを探して", "")
            .replace("メモを探して", "")
            .replace("メモを見せて", "")
            .replace("メモ", "")
            .replace("を見せて", "")
            .replace("を検索して", "")
            .replace("検索", "")
            .replace("探して", "")
            .replace("見せて", "")
            .strip()
        )

        return call_mcp_tool(
            "search_notes",
            {
                "user_id": user_id,
                "keyword": keyword
            }
        )







    # =========================
    # リマインダー系はAIを使わずMCP直行
    # =========================
    if "分後に" in message and ("言って" in message or "教えて" in message or "知らせて" in message):
        m = re.search(r"(\d+)分後に(.+?)(?:と言って|教えて|知らせて)$", message)

        if m:
            minutes = int(m.group(1))
            reminder_text = m.group(2).strip()

            remind_at = (
                datetime.now(timezone(timedelta(hours=9)))
                + timedelta(minutes=minutes)
            ).isoformat()

            return call_mcp_tool(
                "set_reminder",
                {
                    "user_id": user_id,
                    "remind_at": remind_at,
                    "message": reminder_text,
                    "repeat": "none"
                }
            )



    # =========================
    # 自然文の予定確認もAIを使わずMCP直行
    # =========================
    if message in [
        "予定ある？",
        "予定ある",
        "今日の予定",
        "リマインダー確認",
        "予定を教えて"
    ]:
        return call_mcp_tool(
            "list_reminders",
            {
                "user_id": user_id
            }
        )


    # =========================
    # リマインダー一覧はAIを使わずMCP直行
    # =========================
    if message == "リマインダー一覧":
        return call_mcp_tool(
            "list_reminders",
            {
                "user_id": user_id
            }
        )



    # =========================
    # リマインダー削除はAIを使わずMCP直行
    # =========================
    if message.startswith("リマインダー削除"):
        reminder_id = message.replace("リマインダー削除", "").strip()
        reminder_id = unicodedata.normalize("NFKC", reminder_id)

        return call_mcp_tool(
            "cancel_reminder",
            {
                "user_id": user_id,
                "id": int(reminder_id)
            }
        )


    print("===== GENERATE_REPLY START =====")
    print("USER:", user_id)
    print("MESSAGE:", message)

    save_message(user_id, "user", message)

    personalities = [
        "あなたは優しくフレンドリーなAIです。",
        "あなたは少し冗談を言う親しみやすいAIです。",
        "あなたは落ち着いた相談相手のようなAIです。"
    ]

    # 現在時刻をシステムプロンプトに含める。
    # 「5分後」のような相対時間をモデルが正しくISO 8601へ変換するには、
    # 「今が何時か」を明示的に与えておく必要がある(モデル自身は現在時刻を知らない)。
    now_jst = datetime.now(timezone(timedelta(hours=9)))
    now_str = now_jst.strftime("%Y-%m-%dT%H:%M:%S+09:00")

    # 会話履歴(直近8件)には載っていない可能性があるため、
    # 名前だけはAIの判断(get_memoryを呼ぶかどうか)に頼らず、
    # 毎ターン必ずMCPサーバーから直接取得してプロンプトに埋め込む。
    # こうすることで「何ターンか前に名乗ったのに、履歴から流れたら忘れる」
    # という症状を防ぐ。
    try:
        stored_memory = call_mcp_tool(
            "get_all_memory",
            {
                "user_id": user_id
            }
        )
    except Exception as e:
        print("GET ALL MEMORY ERROR:", e)
        stored_memory = ""

    known_facts_block = stored_memory if stored_memory else "(まだ何も記憶していません)"

    system_prompt = f"""
{random.choice(personalities)}

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

ユーザーが「n分後に教えて」「明日の朝リマインドして」のように、
将来のある時点で何かを伝えてほしいと頼んできた場合は、
必ず set_reminder ツールを呼び出してください。
remind_atは上記の現在日時を基準に計算した具体的なISO 8601日時にすること。
「わかりました」と答えるだけでツールを呼ばずに済ませてはいけません。

ユーザーが「毎日」「毎朝」のように繰り返しを希望した場合は、
set_reminderのrepeatパラメータに'daily'を指定してください。
その場合のremind_atは「1回目に送る日時」で構いません(以降は自動で毎日繰り返されます)。
繰り返しを希望していない場合はrepeatを省略するか'none'にしてください。

ユーザーが「今何がセットされてる?」「予定確認して」のように、
登録済みのリマインダーの中身を具体的に知りたい場合は list_reminders を、
「さっきのキャンセルして」のように取り消したい場合はまず list_reminders でidを確認してから
cancel_reminder を呼び出してください。

一方、「どんなセットがある?」「セットって何ができるの?」「使い方教えて」のように、
リマインダー機能そのものについて聞いているだけで、登録済みの中身を尋ねていない場合は
list_reminders を呼ばず、機能の説明として通常の会話で答えてください。
迷った場合は「セットする(予定を登録する)」という動詞的な使い方をしているか、
それとも登録済みの中身を尋ねているかで判断してください。

ユーザーが「もう時間過ぎてるよ」「遅い」「なぜ忘れたの?」のように、
リマインダーが届かなかった/遅れたことへの指摘・不満・感想を述べているだけの場合は、
set_reminderを勝手に呼び出して新しい時刻で登録し直したりしないでください。
謝罪や状況説明など、通常の会話として応答してください。
ユーザーが「もう一度セットして」「〇時に変えて」のように、明確に再設定を
頼んできた場合のみ set_reminder を呼び出してください。
"""

    history = load_history(user_id)

    messages = [{"role": "system", "content": system_prompt}]
    messages += [{"role": r, "content": c} for r, c in history]

    try:
        # 1回目: Groqにツール一覧を渡して呼び出す
        # ツール呼び出しの構文はtemperatureが高いと崩れやすい(Groq/Llama系の既知の傾向)ため、
        # ここは低めのtemperatureにして呼び出し判断を安定させる。
        # 自然な受け答えのランダム性は2回目(最終返信生成)側で確保する。
        forced_tool_call = None  # フォールバックで手動再現したtool_callがあればここに入れる
        forced_tool_args = {}    # forced_tool_callの引数(failed_generationから復元できた分)

        try:
            print("AVAILABLE TOOLS:")
            print([t["function"]["name"] for t in MCP_TOOLS_SCHEMA])

            res = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0,
                max_tokens=1024,
                tools=MCP_TOOLS_SCHEMA,
                tool_choice="auto"
            )
            choice = res.choices[0].message

        except Exception as e:
            # モデルがツール呼び出し構文を壊して生成してしまう(tool_use_failed)ことが
            # まれにあるため、まずtemperatureを変えて1回だけリトライする。
            # (同じtemperature=0で同じmessagesを再送すると、同じ壊れた出力を
            #  再現してしまいやすいため、あえて値を変える)
            print("TOOL CALL GENERATION FAILED, RETRYING:", e)
            try:
                res = client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    temperature=0,
                    max_tokens=1024,
                    tools=MCP_TOOLS_SCHEMA,
                    tool_choice="auto"
                )
                choice = res.choices[0].message

            except Exception as e2:
                # リトライでも壊れた場合のフォールバック:
                # Groqのエラーレスポンスにはmodelが生成しようとした壊れたテキストが
                # failed_generation として含まれている(例: "<function=list_reminders />")。
                # ここから関数名だけ正規表現で拾い、引数なしツール呼び出しとして
                # 手動で再現することで、ユーザーには「エラー」ではなく結果を返す。
                print("TOOL CALL RETRY ALSO FAILED, ATTEMPTING FALLBACK PARSE:", e2)

                failed_name = None
                failed_args = {}

                try:
                    body = getattr(e2, "body", None) or {}
                    failed_gen = body.get("error", {}).get("failed_generation", "")

                    # Groq/Llama系が返す古いfunctionタグ形式を解析
                    # 例:
                    # <function=search_notes{"keyword":"LINE Bot"}</function>
                    # <function=list_reminders />
                    m = re.search(
                        r"<function=([a-zA-Z0-9_]+)\s*(\{.*\})?\s*(?:/?>|</function>)",
                        failed_gen
                    )

                    if m:
                        failed_name = m.group(1)

                        if m.group(2):
                            try:
                                failed_args = json.loads(m.group(2))

                            except Exception as args_err:
                                print(
                                    "FAILED_GENERATION ARGS PARSE ERROR:",
                                    args_err
                                )
                                failed_args = {}

                except Exception as parse_err:
                    print("FAILED_GENERATION PARSE ERROR:", parse_err)

                # フォールバック対象にできるツール。
                # - list_reminders: 引数なしで安全に実行できる
                # - get_memory: 読み取り専用で副作用がないため、keyが復元できなくても安全
                # - save_memory: 保存内容はdispatch_tool_call内でユーザー原文の「」引用を
                #   優先して使うため、JSON引数の復元が多少不完全でも実害が小さい
                # (set_reminder/cancel_reminderは実際の予約/取消という副作用があり、
                #  引数を誤って復元すると影響が大きいため引き続き対象外)
                SAFE_FALLBACK_TOOLS = {"list_reminders", "get_memory", "save_memory"}

                if failed_name in SAFE_FALLBACK_TOOLS:
                    forced_tool_call = failed_name
                    forced_tool_args = failed_args
                    choice = None
                else:
                    # 復元できない場合はそのまま例外を上位に投げて、
                    # 既存のエラーメッセージ分岐(status_code等)に処理させる
                    raise

        # ツール呼び出しが指定された場合はMCPサーバーを実行し、結果を持たせて再度問い合わせる
        tool_calls_happened = bool(forced_tool_call) or bool(choice.tool_calls if choice else False)

        if forced_tool_call:
            # フォールバック経路: モデルの生成が壊れていたため、
            # 疑似的なtool_call情報をこちらで組み立てて同じ処理に合流させる
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
                            "arguments": json.dumps(forced_tool_args, ensure_ascii=False)
                        }
                    }
                ]
            })

            tool_results_by_name = {}
            try:
                tool_result = dispatch_tool_call(user_id, forced_tool_call, forced_tool_args, original_message=message)
            except Exception as e:
                print("MCP TOOL CALL ERROR:", e)
                tool_result = f"ツール実行エラー: {e}"

            tool_results_by_name.setdefault(forced_tool_call, []).append(tool_result)

            messages.append({
                "role": "tool",
                "tool_call_id": fallback_id,
                "content": tool_result
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
                            "arguments": tc.function.arguments
                        }
                    } for tc in choice.tool_calls
                ]
            })

            tool_results_by_name = {}

            for tc in choice.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except Exception:
                    args = {}

                try:
                    tool_result = dispatch_tool_call(user_id, tc.function.name, args, original_message=message)
                except Exception as e:
                    print("MCP TOOL CALL ERROR:", e)
                    tool_result = f"ツール実行エラー: {e}"

                tool_results_by_name.setdefault(tc.function.name, []).append(tool_result)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result
                })

        if tool_calls_happened:
            # list_reminders / get_memory は、日時・id・記憶した値のような
            # 正確な情報をそのまま答える必要があるツール。
            # 2回目のAI呼び出し(temperature=0.85)で自然な文章に言い換えさせると、
            # 値を微妙に取り違えて答えてしまう(ハルシネーション)ことが確認されたため、
            # これらのツールだけが呼ばれた場合は言い換えさせず、
            # MCPサーバーが返した生の結果をそのまま返信として使う。
            # (save_memory等、他のツールも一緒に呼ばれた場合は従来通り2回目の呼び出しを行う)
            PRECISE_TOOLS = {"list_reminders", "get_memory"}
            called_tool_names = set(tool_results_by_name.keys())
            if called_tool_names and called_tool_names.issubset(PRECISE_TOOLS):
                reply = "\n".join(
                    text
                    for tool_name in called_tool_names
                    for text in tool_results_by_name[tool_name]
                )
            else:
                # 2回目: ツール結果を踏まえた最終回答を生成
                #
                # ここまでのmessagesにはtool実行結果がrole="tool"で
                # JSON文字列のまま入っている(例: {"title": "牛乳を買う", "body": "牛乳を買う"})。
                # 指示を与えないと、モデルがこのJSONをそのまま「答え」として
                # 出力してしまう(LINEにJSONがそのまま表示される不具合の原因)ため、
                # 「必ず自然な日本語に言い換えること」を明示的に指示するメッセージを
                # このタイミングでmessagesの末尾に追加してから2回目の呼び出しを行う。
                messages.append({
                    "role": "system",
                    "content": (
                        "直前のtool結果(role: toolのJSON)を踏まえて、ユーザーへの返信を作成してください。\n"
                        "JSON、辞書形式、{ }や \"key\": \"value\" のような記号表現をそのまま出力することは絶対にしないでください。\n"
                        "必ず自然な日本語の会話文に言い換えてください。\n\n"
                        "例:\n"
                        "tool結果が {\"title\": \"牛乳を買う\", \"body\": \"牛乳を買う\"} の場合\n"
                        "→「牛乳を買うというメモがあります」\n\n"
                        "tool結果が複数件の配列の場合は、内容をもとに箇条書きで自然に紹介してください。\n"
                        "tool結果が空、またはメモが見つからなかった場合は「メモは見つかりませんでした」のように伝えてください。"
                    )
                })

                res2 = client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    temperature=0.85,
                    max_tokens=1024
                )
                reply = res2.choices[0].message.content
        else:
            reply = choice.content

    except Exception as e:
        print("AI ERROR:", e)

        # Groqの例外(RateLimitError等)は status_code を持つ。
        # 念のため文字列に "429" が含まれるケースも拾っておく。
        status_code = getattr(e, "status_code", None)

        if status_code == 429 or "429" in str(e):
            reply = (
                "ごめんなさい、今日利用できるAIの上限に達してしまいました🙏\n"
                "しばらく時間をおいてから、もう一度話しかけてみてください。"
            )
        elif status_code == 401 or status_code == 403:
            reply = "AIサービスへの接続設定に問題があるようです。少し時間を置いてもう一度お試しください。"
        elif status_code is not None and status_code >= 500:
            reply = "AIサービス側で一時的な不具合が起きているようです。少ししてからもう一度お試しください。"
        elif "timeout" in str(e).lower() or "timed out" in str(e).lower():
            reply = "応答に時間がかかりすぎたため、一度中断しました。もう一度話しかけてみてください。"
        else:
            reply = "エラーが発生してしまいました。もう一度試してみてください🙏"

    save_message(user_id, "assistant", reply)

    print("===== GENERATE_REPLY END =====")

    return reply


# =========================
# LINE webhook
# =========================
@app.route("/callback", methods=["POST"])
def callback():
    body = request.get_data(as_text=True)
    signature = request.headers.get("X-Line-Signature")

    print("===== CALLBACK RECEIVED =====")
    print("BODY:", body)
    print("SIGNATURE:", signature)

    try:
        handler.handle(body, signature)
    except Exception as e:
        print("===== HANDLER ERROR =====")
        print(e)

    return "OK"

# =========================
# 重複イベント防止
# =========================
# LINEのWebhookは応答が遅いと同じイベントを再送してくることがある。
# (今回、set_reminderの内容が微妙に異なる状態で3重に保存されたのはこれが原因)
# 同じmessage_idを2回以上処理しないよう、直近処理済みIDをメモリに保持する。
# ※ workers=1構成のプロセス内メモリのみで完結する簡易対策。
#   プロセス再起動で消えるが、再送は通常同一プロセスが動いている短時間内に来るため実用上問題ない。
_processed_message_ids = set()
_processed_lock = threading.Lock()
_MAX_TRACKED_IDS = 2000


def _process_and_reply(event, user_id, text):
    """generate_reply〜reply_messageまでを非同期に実行する。
    LINEへのWebhook応答(200 OK)を待たせないためにスレッドへ切り出している。"""
    try:
        reply = generate_reply(user_id, text)

        print("GENERATED REPLY:", repr(reply))

        with ApiClient(configuration) as api:
            MessagingApi(api).reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply)]
                )
            )

        print("REPLY SENT SUCCESS")

    except Exception as e:
        import traceback
        print("===== HANDLE ERROR (async) =====")
        traceback.print_exc()


# =========================
# EVENT HANDLER
# =========================
@handler.add(MessageEvent, message=TextMessageContent)
def handle(event):
    print("===== EVENT TRIGGERED =====")

    try:
        user_id = event.source.user_id
        text = event.message.text
        message_id = event.message.id

        print("USER:", user_id)
        print("TEXT:", text)

        # 同じmessage_idを既に処理済みならスキップ(Webhook再送による二重実行を防ぐ)
        with _processed_lock:
            if message_id in _processed_message_ids:
                print("DUPLICATE EVENT SKIPPED:", message_id)
                return
            _processed_message_ids.add(message_id)
            if len(_processed_message_ids) > _MAX_TRACKED_IDS:
                _processed_message_ids.clear()

        # 実際のAI応答生成・reply送信には数秒〜十数秒かかることがあり、
        # ここで待つとLINE側がタイムアウトして同じイベントを再送してくる原因になる。
        # そのためこの関数(handle)はすぐにreturnし、実処理はバックグラウンドで行う。
        threading.Thread(
            target=_process_and_reply,
            args=(event, user_id, text),
            daemon=True
        ).start()

    except Exception as e:
        print("===== HANDLE ERROR =====")
        print(e)

# =========================
# internal push (MCPサーバーのスケジューラーから呼ばれる)
# =========================
# my-mcp-server の index.js が1分おきに、送信予定時刻を過ぎたリマインダーを
# 見つけるとここへPOSTしてくる。ここでLINEのpush APIを使って実際に送信する。
# MCPサーバーはLINEのトークンを持たない設計のため、送信はこちら側の役割。


# =========================
# AI開発報告 API
# =========================
@app.route("/internal/ai-report", methods=["POST"])
def internal_ai_report():

    provided_key = request.headers.get("x-internal-key")

    if provided_key != INTERNAL_PUSH_KEY:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}

    user_id = data.get("user_id")
    prompt = data.get("prompt")

    if not user_id or not prompt:
        return jsonify({
            "ok": False,
            "error": "user_id and prompt are required"
        }), 400

    try:
        res = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "あなたはAI開発秘書です。簡潔に報告してください。"
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3,
            max_tokens=500
        )

        report = res.choices[0].message.content

        with ApiClient(configuration) as api:
            MessagingApi(api).push_message(
                PushMessageRequest(
                    to=user_id,
                    messages=[TextMessage(text=report)]
                )
            )

        save_message(user_id, "assistant", report)

        return jsonify({"ok": True})

    except Exception as e:
        print("AI REPORT ERROR:", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/internal/push", methods=["POST"])
def internal_push():
    provided_key = request.headers.get("x-internal-key")
    if provided_key != INTERNAL_PUSH_KEY:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    message = data.get("message")

    if not user_id or not message:
        return jsonify({"ok": False, "error": "user_id and message are required"}), 400

    try:
        with ApiClient(configuration) as api:
            MessagingApi(api).push_message(
                PushMessageRequest(
                    to=user_id,
                    messages=[TextMessage(text=message)]
                )
            )
        save_message(user_id, "assistant", message)
        print(f"INTERNAL PUSH SENT: user_id={user_id}")
        return jsonify({"ok": True})

    except Exception as e:
        print("INTERNAL PUSH ERROR:", e)
        return jsonify({"ok": False, "error": str(e)}), 500

# =========================
# health check
# =========================
@app.route("/")
def home():
    return "OK"

@app.route("/health")
def health():
    return jsonify({"ok": True, "service": "line-bot"})

# =========================
# run
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))