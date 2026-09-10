import os
import certifi
from dotenv import load_dotenv
from linebot.v3.messaging import Configuration
from linebot.v3.webhook import WebhookHandler
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from groq import Groq

load_dotenv()

# =========================
# ENV
# =========================
CHANNEL_ACCESS_TOKEN = os.environ["CHANNEL_ACCESS_TOKEN"]
CHANNEL_SECRET = os.environ["CHANNEL_SECRET"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

MCP_SERVER_URL = os.environ["MCP_SERVER_URL"]
MCP_API_KEY = os.environ["MCP_API_KEY"]
INTERNAL_PUSH_KEY = os.environ["INTERNAL_PUSH_KEY"]

AI_REPORT_GITHUB_REPO = os.environ.get("AI_REPORT_GITHUB_REPO", "nonkun12/line-bot")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "")

AI_APP_BUILDER_URL = os.environ.get("AI_APP_BUILDER_URL", "")
AI_APP_BUILDER_SHARED_SECRET = os.environ.get("AI_APP_BUILDER_SHARED_SECRET", "")
AI_APP_BUILDER_TIMEOUT_SECONDS = float(os.environ.get("AI_APP_BUILDER_TIMEOUT_SECONDS", "185"))

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
client = Groq(api_key=GROQ_API_KEY, timeout=15.0, max_retries=1)
MODEL = "openai/gpt-oss-20b"

# Render deployment synchronization marker.
DEPLOY_SYNC_MARKER = "2026-09-11-line-development-route"


# app.py 側の MessageEvent ハンドラーが誤って欠落しても、LINE webhook を
# 受信できるように、ここでハンドラーを登録する。
# 実際の処理は app.py の _process_and_reply に委譲する。
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message_event(event):
    print("[LOG] handle MessageEvent called")
    user_id = None
    try:
        user_id = event.source.user_id
        text = event.message.text
        message_id = event.message.id

        from app import (
            _process_and_reply,
            _processed_lock,
            _processed_message_ids,
            _MAX_TRACKED_IDS,
            _line_reply,
            _line_push,
        )
        from line_development import extract_development_instruction, dispatch_development_workflow
        from db import is_processed_event, create_processed_event
        from e2e_status import record_step

        with _processed_lock:
            if message_id in _processed_message_ids:
                print("DUPLICATE MESSAGE IGNORED (memory):", message_id)
                return

            if is_processed_event(message_id):
                print("DUPLICATE MESSAGE IGNORED (db):", message_id)
                return

            created = create_processed_event(message_id, user_id=user_id, source="line")
            if not created:
                print("DUPLICATE MESSAGE IGNORED (create_failed):", message_id)
                return

            record_step("line_in", True)
            _processed_message_ids[message_id] = True
            if len(_processed_message_ids) > _MAX_TRACKED_IDS:
                _processed_message_ids.popitem(last=False)

        # Development commands are an explicit, isolated LINE protocol.
        # Normal conversation, GitHub lookup commands, and n8n are untouched.
        dev_instruction = extract_development_instruction(text)
        if dev_instruction is not None:
            try:
                reply = dispatch_development_workflow(
                    dev_instruction,
                    user_id=str(user_id),
                    token=GITHUB_TOKEN,
                    repository=AI_REPORT_GITHUB_REPO,
                )
            except Exception as exc:
                import traceback
                print("===== DEVELOPMENT DISPATCH ERROR =====")
                traceback.print_exc()
                reply = f"開発ワークフローの起動処理でエラーが発生しました: {type(exc).__name__}"

            try:
                _line_reply(event.reply_token, reply)
            except Exception as exc:
                # Reply tokens are short-lived. If the direct reply fails, use
                # push messaging so the user still receives the development result.
                print("[LOG] development LINE reply failed; falling back to push:", exc)
                try:
                    _line_push(str(user_id), reply)
                except Exception:
                    print("===== DEVELOPMENT PUSH FALLBACK ERROR =====")
                    import traceback
                    traceback.print_exc()
            return

        threading = __import__("threading")
        threading.Thread(
            target=_process_and_reply,
            args=(event, user_id, text),
            daemon=True,
        ).start()
    except Exception:
        import traceback
        print("===== HANDLE ERROR =====")
        traceback.print_exc()
        if user_id:
            try:
                from app import _line_push
                _line_push(str(user_id), "LINE処理中にエラーが発生しました。ログを確認して復旧します。")
            except Exception:
                print("===== HANDLE ERROR PUSH FAILED =====")
                traceback.print_exc()
