from flask import Flask, request
from linebot.v3.webhook import WebhookHandler
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from groq import Groq
import os
import sqlite3
import json
import random
import threading
import requests

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

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
# timeoutを明示的に指定し、Groq側が詰まってもgunicorn workerごと
# ハングしないようにする(Renderがクラッシュと誤認して再起動する原因になっていた)
client = Groq(api_key=GROQ_API_KEY, timeout=15.0, max_retries=1)

MODEL = "llama-3.3-70b-versatile"
DB = "chat.db"

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
            LIMIT 15
            """, (user_id,)).fetchall()
    except Exception as e:
        print("DB LOAD_HISTORY ERROR:", e)
        return []

    return list(reversed(rows))

# =========================================================
# MCPクライアント(StreamableHTTP / stateless)
# =========================================================
def call_mcp_tool(tool_name, arguments, timeout=10.0):
    """
    my-mcp-server の /mcp エンドポイントへ JSON-RPC で tools/call を送る。
    StreamableHTTPServerTransport はレスポンスを
    application/json または text/event-stream のどちらでも返し得るため両方に対応する。
    """
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
        "Accept": "application/json, text/event-stream"
    }

    res = requests.post(
        MCP_SERVER_URL,
        json=payload,
        headers=headers,
        timeout=timeout
    )
    res.raise_for_status()

    content_type = res.headers.get("content-type", "")

    if "text/event-stream" in content_type:
        # SSE形式: "data: {...}" 行からJSONを取り出す
        data_line = None
        for line in res.text.splitlines():
            if line.startswith("data:"):
                data_line = line[len("data:"):].strip()
        if data_line is None:
            raise RuntimeError("MCP SSEレスポンスにdataが見つかりません")
        body = json.loads(data_line)
    else:
        body = res.json()

    if "error" in body:
        raise RuntimeError(f"MCP error: {body['error']}")

    result = body.get("result", {})
    parts = result.get("content", [])
    texts = [p.get("text", "") for p in parts if p.get("type") == "text"]
    return "\n".join(texts) if texts else ""


# Groq(OpenAI互換)のfunction calling形式でMCPツールを公開する。
# ユーザーごとの記憶を分離するため、モデルには生の key/value だけを
# 触らせ、実際にMCPへ渡す際はサーバー側でuser_idを前置して名前空間を分ける。
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
            "name": "get_memory",
            "description": "以前保存したユーザーの記憶をkeyで取得する",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "取得したい記憶の項目名"}
                },
                "required": ["key"]
            }
        }
    }
]

def dispatch_tool_call(user_id, name, arguments):
    """LINEのuser_idごとに記憶が混ざらないよう、keyをここで名前空間化してMCPへ渡す"""
    namespaced_key = f"{user_id}:{arguments.get('key', '')}"

    if name == "save_memory":
        return call_mcp_tool("save_memory", {
            "key": namespaced_key,
            "value": arguments.get("value", "")
        })

    if name == "get_memory":
        return call_mcp_tool("get_memory", {
            "key": namespaced_key
        })

    return f"不明なツールです: {name}"


# =========================
# AI本体(返信生成 + MCPツール呼び出しループ)
# =========================
def generate_reply(user_id, message):
    print("===== GENERATE_REPLY START =====")
    print("USER:", user_id)
    print("MESSAGE:", message)

    save_message(user_id, "user", message)

    personalities = [
        "あなたは優しくフレンドリーなAIです。",
        "あなたは少し冗談を言う親しみやすいAIです。",
        "あなたは落ち着いた相談相手のようなAIです。"
    ]

    system_prompt = f"""
{random.choice(personalities)}

ユーザーについて覚えておくべきことがあれば save_memory ツールで保存し、
思い出す必要があれば get_memory ツールで確認してください。
ツールのkeyはユーザーごとに自動で区別されるので、あなたはkey名(name, hobbyなど)だけ気にしてください。
"""

    history = load_history(user_id)

    messages = [{"role": "system", "content": system_prompt}]
    messages += [{"role": r, "content": c} for r, c in history]

    try:
        # 1回目: Groqにツール一覧を渡して呼び出す
        res = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.85,
            max_tokens=1024,
            tools=MCP_TOOLS_SCHEMA,
            tool_choice="auto"
        )

        choice = res.choices[0].message

        # ツール呼び出しが指定された場合はMCPサーバーを実行し、結果を持たせて再度問い合わせる
        if choice.tool_calls:
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

            for tc in choice.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except Exception:
                    args = {}

                try:
                    tool_result = dispatch_tool_call(user_id, tc.function.name, args)
                except Exception as e:
                    print("MCP TOOL CALL ERROR:", e)
                    tool_result = f"ツール実行エラー: {e}"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result
                })

            # 2回目: ツール結果を踏まえた最終回答を生成
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
        reply = "AIエラーが発生しました"

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
# EVENT HANDLER
# =========================
@handler.add(MessageEvent, message=TextMessageContent)
def handle(event):
    print("===== EVENT TRIGGERED =====")

    try:
        user_id = event.source.user_id
        text = event.message.text

        print("USER:", user_id)
        print("TEXT:", text)

        # 返信の生成 → 送信を最優先で行う(reply_tokenは約1分で失効するため)
        reply = generate_reply(user_id, text)

        with ApiClient(configuration) as api:
            MessagingApi(api).reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply)]
                )
            )

        print("REPLY SENT SUCCESS")

    except Exception as e:
        print("===== HANDLE ERROR =====")
        print(e)

# =========================
# health check
# =========================
@app.route("/")
def home():
    return "OK"

# =========================
# run
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))