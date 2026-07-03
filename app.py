from flask import Flask, request
import requests
import os

app = Flask(__name__)

LINE_TOKEN = os.environ.get("LINE_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        body = request.json
        print("受信:", body)

        # ① eventsチェック（超重要）
        if not body or "events" not in body or len(body["events"]) == 0:
            return "OK"

        event = body["events"][0]

        # ② メッセージ以外は無視
        if event.get("type") != "message":
            return "OK"

        if event["message"].get("type") != "text":
            return "OK"

        # ③ ユーザーのメッセージ取得
        msg = event["message"]["text"]
        reply_token = event["replyToken"]

        # ④ Gemini呼び出し
        answer = gemini(msg)

        # ⑤ LINE返信
        reply(reply_token, answer)

    except Exception as e:
        print("ERROR:", str(e))

    return "OK"


# ---------------------------
# Gemini API
# ---------------------------
def gemini(text):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

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
        print("Gemini:", data)

        return data["candidates"][0]["content"]["parts"][0]["text"]

    except Exception as e:
        print("Gemini Error:", e)
        return "AIの応答でエラーが発生しました"


# ---------------------------
# LINE返信
# ---------------------------
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


# ---------------------------
# 起動
# ---------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
