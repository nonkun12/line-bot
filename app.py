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

app = Flask(__name__)

# =========================
# 環境変数（必須）
# =========================
CHANNEL_ACCESS_TOKEN = os.environ.get("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.environ.get("CHANNEL_SECRET")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

if not CHANNEL_ACCESS_TOKEN or not CHANNEL_SECRET or not GROQ_API_KEY:
    print("❌ 環境変数不足")
    raise Exception("Missing env vars")

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
client = Groq(api_key=GROQ_API_KEY)

# =========================
# モデル（最新安定）
# =========================
MODEL = "llama-3.1-70b-versatile"

# =========================
# DB
# =========================
DB = "chat.db"

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
init_db()

# =========================
# 保存
# =========================
def save_message(user_id, role, content):
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO messages(user_id, role, content) VALUES (?, ?, ?)",
                (user_id, role, content)
            )

            # 最新100件保持
            conn.execute("""
            DELETE FROM messages
            WHERE user_id = ?
            AND id NOT IN (
                SELECT id FROM messages
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT 100
            )
            """, (user_id, user_id))
    except Exception as e:
        print("DB error:", e)

# =========================
# 履歴
# =========================
def load_history(user_id, limit=20):
    try:
        with get_conn() as conn:
            rows = conn.execute("""
            SELECT role, content
            FROM messages
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """, (user_id, limit)).fetchall()

        rows.reverse()

        messages = [
            {
                "role": "system",
                "content": "あなたは親切で自然な日本語を話すAIです。"
            }
        ]

        for role, content in rows:
            messages.append({"role": role, "content": content})

        return messages

    except Exception as e:
        print("history error:", e)
        return [{"role": "system", "content": "あなたはAIです"}]

# =========================
# AI
# =========================
def ask_ai(user_id, message):
    try:
        save_message(user_id, "user", message)

        messages = load_history(user_id)

        completion = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=1024
        )

        reply = completion.choices[0].message.content

        save_message(user_id, "assistant", reply)

        return reply

    except Exception as e:
        print("AI error:", e)
        return "AIエラーが発生しました"

# =========================
# LINE webhook
# =========================
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    handler.handle(body, signature)

    return "OK"

# =========================
# ヘルスチェック（超重要）
# =========================
@app.route("/")
def home():
    return "OK"

# =========================
# メッセージ処理
# =========================
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
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
# 起動
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)