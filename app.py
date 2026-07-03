from flask import Flask, request, abort
import os
import traceback

from google import genai

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

# ★ デバッグ出力（重要）
print("===== ENV CHECK =====")
print("LINE_CHANNEL_ACCESS_TOKEN =", "OK" if LINE_CHANNEL_ACCESS_TOKEN else "NG")
print("LINE_CHANNEL_SECRET =", "OK" if LINE_CHANNEL_SECRET else "NG")
print("GEMINI_API_KEY =", GEMINI_API_KEY)
print("=====================")

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
# Gemini初期化（新SDK）
# ======================
client = genai.Client(api_key=GEMINI_API_KEY)

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
    except Exception:
        traceback.print_exc()
        abort(500)

    return "OK"

# ======================
# メイン処理
# ======================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):

    user_text = event.message.text

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=user_text
        )

        reply_text = response.text

        print("===== GEMINI RESPONSE =====")
        print(reply_text)

    except Exception as e:
        print("===== GEMINI ERROR =====")
        traceback.print_exc()
        reply_text = f"Geminiエラー:\n{e}"

    try:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
    except Exception:
        traceback.print_exc()

# ======================
# start
# ======================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)