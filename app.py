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

        # 安全チェック（超重要）
        if not body or "events" not in body or len(body["events"]) == 0:
            return "OK"

        event = body["events"][0]

        if event.get("type") != "message":
            return "OK"

        if event["message"].get("type") != "text":
            return "OK"

        msg = event["message"]["text"]
        reply_token = event["replyToken"]

        # Gemini
        answer = gemini(msg)

        # LINE返信
        reply(reply_token, answer)

    except Exception as e:
        print("Webhook Error:", str(e))

    return "OK"


# =========================
# Gemini API（修正版）
# =========================
def gemini(text):
    # ★ここが重要（最新版モデル）
    url = (
        "https://generativelanguage.googleapis.com/v1/models/"
        "gemini-1.5-flash-latest:generateContent"
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

        # エラーチェック
        if "error" in data:
            return "Geminiエラー: " + data["error"]["message"]

        if "candidates" not in data or len(data["candidates"]) == 0:
            return "AIが空の応答を返しました"

        return data["candidates"][0]["content"]["parts"][0]["text"]

    except Exception as e:
        return f"Gemini通信エラー: {str(e)}"


# =========================
# LINE返信
# =========================
def reply(token, text):
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
                "text": text[:4900]  # LINE制限対策
            }
        ]
    }

    requests.post(url, headers=headers, json=payload)


# =========================
# 起動（Render用）
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
