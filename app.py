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

app = Flask(__name__)

# =========================
# ENV
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
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            role TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS memory(
            user_id TEXT PRIMARY KEY,
            profile TEXT,
            score INTEGER DEFAULT 0
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
# 記憶取得
# =========================
def get_memory(user_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT profile, score FROM memory WHERE user_id=?",
            (user_id,)
        ).fetchone()

    if row:
        try:
            return json.loads(row[0]), row[1]
        except:
            return {}, 0

    return {}, 0

# =========================
# 記憶更新（重要なものだけ）
# =========================
def update_memory(user_id, text):
    prompt = f"""
ユーザー情報を抽出してJSONで返してください。

項目:
- name
- hobby
- job
- personality
- important_notes

会話:
{text}

JSONのみ:
"""

    try:
        res = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )

        data = json.loads(res.choices[0].message.content)

    except:
        data = {}

    with get_conn() as conn:
        conn.execute("""
        INSERT INTO memory(user_id, profile, score)
        VALUES (?, ?, 1)
        ON CONFLICT(user_id)
        DO UPDATE SET
            profile=excluded.profile,
            score=memory.score + 1
        """, (user_id, json.dumps(data, ensure_ascii=False)))

# =========================
# 忘却（人間っぽさの核）
# =========================
def decay_memory(user_id):
    with get_conn() as conn:
        conn.execute("""
        UPDATE memory
        SET score = MAX(score - 1, 0)
        WHERE user_id=?
        """, (user_id,))

# =========================
# 履歴取得
# =========================
def load_history(user_id):
    with get_conn() as conn:
        rows = conn.execute("""
        SELECT role, content FROM messages
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 15
        """, (user_id,)).fetchall()

    return list(reversed(rows))

# =========================
# AI本体（最終形）
# =========================
def ask_ai(user_id, message):
    save_message(user_id, "user", message)

    memory, score = get_memory(user_id)

    # 人間っぽい性格固定
    personalities = [
        "あなたは優しくフレンドリーなAIです。",
        "あなたは少し冗談を言う親しみやすいAIです。",
        "あなたは落ち着いた相談相手のようなAIです。"
    ]

    system_prompt = f"""
{random.choice(personalities)}

ユーザー情報（記憶）:
{memory}

関係性スコア:
{score}

ルール:
- スコアが高いほど親しく話す
- 初対面は丁寧
- 少しだけ曖昧さを持たせる（人間っぽさ）
"""

    history = load_history(user_id)

    messages = [{"role": "system", "content": system_prompt}]
    messages += [{"role": r, "content": c} for r, c in history]

    res = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.85,
        max_tokens=1024
    )

    reply = res.choices[0].message.content

    save_message(user_id, "assistant", reply)

    # ★人間化の核心
    update_memory(user_id, message + " " + reply)
    decay_memory(user_id)

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
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))