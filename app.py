from flask import Flask, request
import requests
import os

app = Flask(__name__)

LINE_TOKEN = os.environ.get("LINE_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# LINE webhook
@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.json

    try:
        event = body["events"][0]
        msg = event["message"]["text"]
        reply_token = event["replyToken"]

        answer = gemini(msg)
        reply(reply_token, answer)

    except Exception as e:
        print(e)

    return "OK"


def gemini(text):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [
            {"parts": [{"text": text}]}
        ]
    }

    r = requests.post(url, json=payload)
    data = r.json()

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except:
        return "エラーが発生しました"


def reply(token, text):
    url = "https://api.line.me/v2/bot/message/reply"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}"
    }

    payload = {
        "replyToken": token,
        "messages": [
            {"type": "text", "text": text}
        ]
    }

    requests.post(url, headers=headers, json=payload)


if __name__ == "__main__":
    app.run()