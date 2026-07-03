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

app = Flask(__name__)

# =========================
# 環境変数
# =========================
CHANNEL_ACCESS_TOKEN = os.environ["CHANNEL_ACCESS_TOKEN"]
CHANNEL_SECRET = os.environ["CHANNEL_SECRET"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
client = Groq(api_key=GROQ_API_KEY)

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
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            role TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            user_id TEXT PRIMARY KEY,
            profile TEXT
        )
        """)

init_db()

# =========================
# 会話保存
# =========================
def save_message(user_id, role, content):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO messages(user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content)
        )

# =========================
# 長期記憶取得
# =========================
def get_memory(user_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT profile FROM memory WHERE user_id=?",
            (user_id,)
        ).fetchone()

    if row:
        return row[0]
    return ""

# =========================
# 長期記憶更新（重要）
# =========================
def update_memory(user_id, text):
    prompt = f"""
この会話からユーザー情報を抽出してJSONで返してください。

抽出項目:
- name（名前）
- hobby（趣味）
- job（仕事）
- notes（その他重要情報）

会話:
{text}

JSONのみ返答:
"""

    res = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2
    )

    try:
        profile = res.choices[0].message.content

        with get_conn() as conn:
            conn.execute("""
            INSERT INTO memory(user_id, profile)
            VALUES (?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET profile=excluded.profile
            """, (user_id, profile))

    except:
        pass

# =========================
# 会話履歴
# =========================
def load_history(user_id):
    with get_conn() as conn:
        rows = conn.execute("""
        SELECT role, content FROM messages
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 20
        """, (user_id,)).fetchall()

    rows.reverse()

    return rows

# =========================
# AI
# =========================
def ask_ai(user_id, message):
    save_message(user_id, "user", message)

    history = load_history(user_id)
    memory = get_memory(user_id)

    system_prompt = f"""
あなたは人間のように記憶するAIです。

ユーザーの長期記憶:
{memory}

この情報を踏まえて自然に会話してください。
"""

    messages = [{"role": "system", "content": system_prompt}]
    messages += [{"role": r, "content": c} for r, c in history]

    res = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.7,
        max_tokens=1024
    )

    reply = res.choices[0].message.content

    save_message(user_id, "assistant", reply)

    # ★重要：会話から記憶更新
    update_memory(user_id, message + " / " + reply)

    return reply

# =========================
# LINE webhook
# =========================
@app.route("/callback", methods=["POST"])
def callback():
    body = request.get_data(as_text=True)
    signature = request.headers.get("X-Line-Signature")
    handler.handle(body, signature)
    return "OK"

@handler.add(MessageEvent, message=TextMessageContent)
def handle(event):
    user_id = event.source.user_id
    text = event.message.text

    reply = ask_ai(user_id, text)

    with ApiClient(configuration) as api:
        MessagingApi(api).reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply)]
            )
        )

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
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)