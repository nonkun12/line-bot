import os
import certifi
from dotenv import load_dotenv
from linebot.v3.messaging import (
    ApiClient,
    AudioMessage,
    Configuration,
    MessagingApi,
    MessagingApiBlob,
    PushMessageRequest,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhook import WebhookHandler
from linebot.v3.webhooks import AudioMessageContent, MessageEvent, TextMessageContent
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
VOICE_PUBLIC_BASE_URL = os.environ.get("VOICE_PUBLIC_BASE_URL", "https://line-bot-yvea.onrender.com").rstrip("/")

AI_APP_BUILDER_URL = os.environ.get("AI_APP_BUILDER_URL", "")
AI_APP_BUILDER_SHARED_SECRET = os.environ.get("AI_APP_BUILDER_SHARED_SECRET", "")
AI_APP_BUILDER_TIMEOUT_SECONDS = float(os.environ.get("AI_APP_BUILDER_TIMEOUT_SECONDS", "185"))

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
client = Groq(api_key=GROQ_API_KEY, timeout=15.0, max_retries=1)
MODEL = "openai/gpt-oss-20b"

# Render deployment synchronization marker.
DEPLOY_SYNC_MARKER = "2026-09-12-line-voice-e2e"


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
            def _run_development_async():
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
                    _line_push(str(user_id), reply)
                except Exception:
                    print("===== DEVELOPMENT PUSH ERROR =====")
                    import traceback
                    traceback.print_exc()

            threading = __import__("threading")
            threading.Thread(
                target=_run_development_async,
                daemon=True,
                name="line-development-dispatch",
            ).start()
            return

        threading = __import__("threading")
        threading.Thread(
            target=_process_and_reply,
            args=(event, user_id, text),
            daemon=True,
        ).start()
    except Exception:
        import traceback
        traceback.print_exc()
        if user_id:
            try:
                from app import _line_push
                _line_push(str(user_id), "LINE処理中にエラーが発生しました。ログを確認して復旧します。")
            except Exception:
                print("===== HANDLE ERROR PUSH FAILED =====")
                traceback.print_exc()


@handler.add(MessageEvent, message=AudioMessageContent)
def handle_audio_message_event(event):
    """Receive LINE audio, run STT -> Core -> TTS, and return an audio message."""
    print("[LOG] handle AudioMessageEvent called")
    user_id = getattr(event.source, "user_id", None)
    message_id = getattr(event.message, "id", None)
    if not message_id:
        return

    from app import _line_push, _processed_lock, _processed_message_ids, _MAX_TRACKED_IDS
    from db import is_processed_event, create_processed_event
    from e2e_status import record_step

    with _processed_lock:
        if message_id in _processed_message_ids or is_processed_event(message_id):
            print("DUPLICATE AUDIO MESSAGE IGNORED:", message_id)
            return
        if not create_processed_event(message_id, user_id=user_id, source="line_audio"):
            print("DUPLICATE AUDIO MESSAGE IGNORED (create_failed):", message_id)
            return
        record_step("line_in", True)
        _processed_message_ids[message_id] = True
        if len(_processed_message_ids) > _MAX_TRACKED_IDS:
            _processed_message_ids.popitem(last=False)

    import threading
    threading.Thread(
        target=_process_audio_message,
        args=(event, str(user_id or ""), str(message_id), VOICE_PUBLIC_BASE_URL),
        daemon=True,
        name="line-voice-e2e",
    ).start()


def _process_audio_message(event, user_id: str, message_id: str, public_base_url: str) -> None:
    """Heavy voice work runs outside the webhook request thread."""
    from app import app, _line_push
    from core.line_voice import estimate_audio_duration_ms, store_audio
    from core.voice import openai_transcribe_audio, openai_tts_audio
    from core.channel import handle_channel_request
    from e2e_status import record_step

    try:
        # LINE's audio content endpoint is a separate blob API in SDK v3.
        with ApiClient(configuration) as api_client:
            blob_api = MessagingApiBlob(api_client)
            audio = blob_api.get_message_content(message_id=message_id)

        transcript = openai_transcribe_audio(
            audio,
            "line-voice.m4a",
            "audio/m4a",
        ).strip()
        if not transcript:
            raise ValueError("voice transcription returned empty text")

        ai_response = handle_channel_request(
            app.ai_gateway,
            user_id,
            transcript,
            "voice",
            metadata={
                "route": "line_callback_audio",
                "input": "line_audio",
                "message_id": message_id,
            },
        )
        reply_text = str(ai_response.text or "").strip()
        if not reply_text:
            raise ValueError("voice Core returned empty reply")

        tts_audio, mime_type = openai_tts_audio(reply_text)
        token = store_audio(tts_audio, mime_type=mime_type)
        audio_url = f"{public_base_url}/api/voice/audio/{token}"
        duration_ms = estimate_audio_duration_ms(reply_text)

        with ApiClient(configuration) as api_client:
            line_api = MessagingApi(api_client)
            try:
                line_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[
                            AudioMessage(
                                original_content_url=audio_url,
                                duration=duration_ms,
                            )
                        ],
                    )
                )
                record_step("line_out", True)
                return
            except Exception:
                # The reply token can expire while STT/TTS is running; use push as
                # the recovery path so a successful voice generation is not lost.
                if not user_id:
                    raise
                line_api.push_message(
                    PushMessageRequest(
                        to=user_id,
                        messages=[
                            AudioMessage(
                                original_content_url=audio_url,
                                duration=duration_ms,
                            )
                        ],
                    )
                )
                record_step("line_out", True)
    except Exception:
        app.logger.exception("LINE AUDIO PIPELINE ERROR")
        if user_id:
            try:
                _line_push(user_id, "音声処理でエラーが発生しました。もう一度音声を送ってください。")
            except Exception:
                app.logger.exception("LINE AUDIO FALLBACK PUSH ERROR")
        else:
            record_step("line_out", False, error="voice_pipeline_failed", error_location="config._process_audio_message")
