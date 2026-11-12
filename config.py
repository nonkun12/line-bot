import os
import uuid
import httpx
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
ORCA_TASK_API_URL = os.environ.get("ORCA_TASK_API_URL", "").strip()
ORCA_TASK_API_TOKEN = os.environ.get("ORCA_TASK_API_TOKEN", "").strip()

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


def _register_orca_task(message: str, message_id: str):
    """Explicit LINE task intake only; stores a task in Cloudflare D1 without executing it."""
    prefixes = ("タスク登録:", "タスク登録：")
    prefix = next((item for item in prefixes if message.startswith(item)), None)
    if prefix is None:
        return None

    request_text = message[len(prefix):].strip()
    if not request_text:
        return False, "タスク内容が空です。「タスク登録: 依頼内容」の形式で送ってください。", False
    if len(request_text.encode("utf-8")) > 6000:
        return False, "依頼文が長すぎます。6,000バイト以内にしてください。", False
    if not ORCA_TASK_API_URL or not ORCA_TASK_API_TOKEN:
        return False, "Cloudflare受付設定が未完了です。依頼は登録されていません。", False

    payload = {
        "task_id": f"line-{uuid.uuid4().hex}",
        "request_text": request_text,
        "source_event_id": str(message_id),
    }
    try:
        response = httpx.post(
            ORCA_TASK_API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {ORCA_TASK_API_TOKEN}"},
            timeout=8.0,
        )
    except httpx.TransportError:
        return False, "Cloudflareへの接続に失敗しました。依頼は未確認です。時間をおいて再送してください。", True

    if response.status_code >= 500:
        return False, "Cloudflare側で一時エラーが発生しました。依頼は未確認です。再送してください。", True
    if response.status_code not in (200, 201):
        return False, f"Cloudflare受付が拒否されました（HTTP {response.status_code}）。依頼は登録されていません。", False

    try:
        result = response.json()
        task = result.get("task", result) if isinstance(result, dict) else {}
        task_id = task.get("task_id") if isinstance(task, dict) else None
        status = task.get("status", "queued") if isinstance(task, dict) else "queued"
    except (ValueError, AttributeError):
        return False, "Cloudflareの応答を確認できませんでした。登録状態を確認してから再送してください。", True

    return True, f"Cloudflare D1に受付しました。状態: {status} / Task ID: {task_id or '受付済み'}（この段階では実行していません）", False


def _register_orca_distributed_loop_task(message: str, message_id: str, user_id: str | None):
    """Register a bounded loop request in D1; never dispatch or execute it."""
    prefixes = ("分散Loop登録:", "分散Loop登録：")
    prefix = next((item for item in prefixes if message.startswith(item)), None)
    if prefix is None:
        return None
    request_text = message[len(prefix):].strip()
    if not request_text or len(request_text.encode("utf-8")) > 6000:
        return False, "分散Loop依頼が空か、6,000バイトを超えています。", False
    from core.orca_distributed_loop_intake import build_distributed_loop_task_payload
    try:
        payload = build_distributed_loop_task_payload(
            task_id=f"line-loop-{uuid.uuid4().hex}",
            request_text=request_text,
            source_event_id=message_id,
            user_id=user_id,
        )
    except ValueError as exc:
        return False, f"分散Loop受付を拒否しました: {exc}", False
    if not ORCA_TASK_API_URL or not ORCA_TASK_API_TOKEN:
        return False, "Orca D1接続設定が未完了です。登録していません。", False
    try:
        response = httpx.post(
            ORCA_TASK_API_URL, json=payload,
            headers={"Authorization": f"Bearer {ORCA_TASK_API_TOKEN}"},
            timeout=8.0,
        )
    except httpx.TransportError:
        return False, "Orca D1への接続結果を確認できません。再送前に状態確認してください。", True
    if response.status_code >= 500:
        return False, "Orca D1が一時エラーです。登録状態を確認してから再送してください。", True
    if response.status_code not in (200, 201):
        return False, f"Orca D1受付が拒否されました（HTTP {response.status_code}）。", False
    try:
        result = response.json()
        task = result.get("task", {}) if isinstance(result, dict) else {}
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or task.get("task_type") != "distributed_loop" or task.get("max_tasks") != payload["max_tasks"]:
            return False, "受付応答のタスク種別・上限を検証できません。実行していません。", True
    except (ValueError, AttributeError):
        return False, "受付応答を検証できません。状態確認が必要です。", True
    return True, f"分散LoopをD1に登録しました（未実行）。Task ID: {task_id} / 上限: {payload['max_tasks']}。実行Workerは未接続です。承認する場合は「分散Loop承認: {task_id}」を送ってください。", False


def _approve_orca_distributed_loop_task(message: str, user_id: str | None):
    prefixes = ("分散Loop承認:", "分散Loop承認：")
    prefix = next((item for item in prefixes if message.startswith(item)), None)
    if prefix is None:
        return None
    task_id = message[len(prefix):].strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", task_id):
        return False, "Task IDの形式が正しくありません。"
    from core.orca_task_approval import is_valid_line_user_id
    from core.orca_distributed_loop_approval import build_distributed_loop_approval_payload
    if not is_valid_line_user_id(user_id):
        return False, "LINE本人確認ができないため承認できません。"
    if not ORCA_TASK_API_URL or not ORCA_TASK_API_TOKEN or len(ORCA_TASK_APPROVAL_HMAC_KEY) < 32:
        return False, "承認用の安全設定が未完了です。承認していません。"
    url = ORCA_TASK_API_URL.rstrip("/") + "/tasks/" + task_id
    headers = {"Authorization": f"Bearer {ORCA_TASK_API_TOKEN}"}
    try:
        response = httpx.get(url, headers=headers, timeout=8.0)
        if response.status_code != 200:
            return False, f"タスクを取得できません（HTTP {response.status_code}）。承認していません。"
        result = response.json()
        task = result.get("task") if isinstance(result, dict) else None
        if not isinstance(task, dict) or task.get("task_id") != task_id:
            return False, "タスク応答が不正です。承認していません。"
        if task.get("status") != "queued" or task.get("task_type") != "distributed_loop":
            return False, "対象は未承認の分散Loopタスクではありません。"
        max_tasks = task.get("max_tasks")
        payload = build_distributed_loop_approval_payload(
            task_id, task.get("request_text"), user_id, max_tasks,
            ORCA_TASK_APPROVAL_HMAC_KEY,
        )
        approved = httpx.post(url + "/approve", json=payload, headers=headers, timeout=8.0)
    except (httpx.TransportError, ValueError, KeyError, TypeError):
        return False, "承認APIとの通信または応答検証に失敗しました。承認していません。"
    if approved.status_code != 200:
        return False, f"承認は拒否されました（HTTP {approved.status_code}）。"
    try:
        result = approved.json()
    except ValueError:
        return False, "承認結果を確認できません。"
    if not isinstance(result, dict) or result.get("approved") is not True:
        return False, "承認結果を確認できません。"
    return True, f"分散Loop Task {task_id} の本人承認を記録しました（上限 {max_tasks}）。ただし専用Worker未接続のため、まだ実行されません。"


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
        from distributed_loop_trigger import request_distributed_loop
        from db import is_processed_event, create_processed_event, delete_processed_event
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

        # Distributed-loop registration and approval are separate from the
        # legacy direct-dispatch command. Neither route executes a loop.
        loop_approval_result = _approve_orca_distributed_loop_task(text, user_id)
        if loop_approval_result is not None:
            _, loop_approval_reply = loop_approval_result
            _line_push(str(user_id or ""), loop_approval_reply)
            return

        loop_intake_result = _register_orca_distributed_loop_task(text, message_id, user_id)
        if loop_intake_result is not None:
            _, loop_intake_reply, retryable = loop_intake_result
            if retryable:
                with _processed_lock:
                    _processed_message_ids.pop(message_id, None)
                    delete_processed_event(message_id)
            _line_push(str(user_id or ""), loop_intake_reply)
            return

        # Explicit Cloudflare app-development intake remains isolated.
        intake_result = _register_orca_task(text, message_id)
        if intake_result is not None:
            accepted, intake_reply, retryable = intake_result
            if retryable:
                # Allow a LINE redelivery to retry a transient D1/API failure.
                # source_event_id makes a timeout-after-commit retry idempotent.
                with _processed_lock:
                    _processed_message_ids.pop(message_id, None)
                    delete_processed_event(message_id)
            try:
                _line_push(str(user_id), intake_reply)
            except Exception:
                import traceback
                print("===== ORCA TASK INTAKE PUSH ERROR =====")
                traceback.print_exc()
            return

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

        # Distributed Loop is a dedicated LINE protocol and must be decided
        # before normal AI routing. This direct entry gate prevents the command
        # from falling through to the normal agent/supervisor path.
        loop_handled, loop_reply = request_distributed_loop(str(user_id or ""), text)
        print(
            "[DISTRIBUTED LOOP ENTRY] "
            f"handled={loop_handled} user_present={bool(user_id)}",
            flush=True,
        )
        if loop_handled:
            def _run_distributed_loop_async():
                try:
                    _line_push(str(user_id), loop_reply)
                except Exception:
                    print("===== DISTRIBUTED LOOP PUSH ERROR =====")
                    import traceback
                    traceback.print_exc()

            threading = __import__("threading")
            threading.Thread(
                target=_run_distributed_loop_async,
                daemon=True,
                name="line-distributed-loop-dispatch",
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
