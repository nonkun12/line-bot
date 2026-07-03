from flask import Flask, request
import requests
import os

app = Flask(__name__)

LINE_TOKEN = os.environ.get("LINE_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")


# =========================
# LINE Webhook
# =========================
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        body = request.json
        print("受信:", body)

        # 空イベント対策
        if not body or "events" not in body or len(body["events"]) == 0:
            return "OK"

        event = body["events"][0]

        # メッセージ以外無視
        if event.get("type") != "message":
            return "OK"

        if event["message"].get("type") != "text":
            return "OK"

        user_text = event["message"]["text"]
        reply_token = event["replyToken"]

        # Gemini呼び出し
        answer = gemini(user_text)

        # LINE返信
        reply_to_line(reply_token, answer)

    except Exception as e:
        print("Webhook Error:", str(e))

    return "OK"


# =========================
# Gemini API（最新安定）
# =========================
def gemini(text):
    # ★ 安定モデル（ここ重要）
    url = (
        "https://generativelanguage.googleapis.com/v1/models/"
        "gemini-1.5-pro:generateContent"
        "?key=" + GEMINI_API_KEY
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": text}
                ]
            }
        ]
    }

    try:
        r = requests.post(url, json=payload)
        data = r.json()

        print("Gemini Response:", data)

        # エラー処理
        if "error" in data:
            return "Geminiエラー: " + data["error"]["message"]

        # 安全チェック
        if "candidates" not in data or len(data["candidates"]) == 0:
            return "AIの応答が空でした"

        return data["candidates"][0]["content"]["parts"][0]["text"]

    except Exception as e:
        return "Gemini通信エラー: " + str(e)


# =========================
# LINE返信
# =========================
def reply_to_line(token, text):
    url = "https://api.line.me/v2/bot/message/reply"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}"
    }

    payload = {
        "replyToken": token,
        "messages": [
            {
                "type": "text",
                "text": text[:4900]
            }
        ]
    }

    requests.post(url, headers=headers, json=payload)


# =========================
# 起動
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
