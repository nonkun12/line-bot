from flask import Flask, request
from linebot.v3.webhook import WebhookHandler
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3 import WebhookParser
from groq import Groq
import os

app = Flask(__name__)

# LINE
CHANNEL_ACCESS_TOKEN = os.environ["CHANNEL_ACCESS_TOKEN"]
CHANNEL_SECRET = os.environ["CHANNEL_SECRET"]

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# Groq
client = Groq(
    api_key=os.environ["GROQ_API_KEY"]
)


def ask_ai(message):
    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "user",
                "content": message,
            }
        ],
    )

    return completion.choices[0].message.content


@app.route("/callback", methods=["POST"])
def callback():

    signature = request.headers["X-Line-Signature"]

    body = request.get_data(as_text=True)

    handler.handle(body, signature)

    return "OK"


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):

    user_message = event.message.text

    reply = ask_ai(user_message)

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply)],
            )
        )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))