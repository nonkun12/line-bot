from flask import Flask, request, abort
import os
import traceback

import google.generativeai as genai

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# ======================
# 環境変数
# ======================
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ======================
# 安全チェック
# ======================
if not LINE_CHANNEL_ACCESS_TOKEN:
    raise Exception("LINE_CHANNEL_ACCESS_TOKEN missing")

if not LINE_CHANNEL_SECRET:
    raise Exception("LINE_CHANNEL_SECRET missing")

if not GEMINI_API_KEY:
    raise Exception("GEMINI_API_KEY missing")

# ======================
# LINE初期化
# ======================
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ======================
# Gemini初期化（安定版）
# ======================
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# ======================
# Webhook
# ======================
@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.get_data(as_text=True)
    signature = request.headers.get("X-Line-Signature")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid Signature")
        abort(400)
    except Exception as e:
        print("Webhook ERROR:", str(e))
        traceback.print_exc()
        abort(500)

    return "OK"

# ======================
# メイン処理
# ======================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):

    user_text = event.message.text
    print("===== USER MESSAGE =====")
    print(user_text)

    reply_text = ""

    # --- Gemini処理 ---
    try:
        response = model.generate_content(user_text)
        reply_text = response.text
        print("===== GEMINI RESPONSE =====")
        print(reply_text)

    except Exception as e:
        print("===== GEMINI ERROR =====")
        print(str(e))
        traceback.print_exc()
        reply_text = "Geminiエラーが発生しました"

    # --- LINE返信 ---
    try:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
        print("===== LINE REPLY OK =====")

    except Exception as e:
        print("===== LINE ERROR =====")
        print(str(e))
        traceback.print_exc()

# ======================
# Render用起動
# ======================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)