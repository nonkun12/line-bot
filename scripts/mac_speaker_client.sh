#!/bin/bash
set -euo pipefail

# Mac AI Speaker client:
# microphone -> STT -> shared AI Secretary Core -> TTS -> Mac speaker.
# Server-side APIs already exist; this script is intentionally dependency-light.

: "${VOICE_SERVER_BASE_URL:?Set VOICE_SERVER_BASE_URL, e.g. https://line-bot-yvea.onrender.com}"
: "${INTERNAL_PUSH_KEY:?Set INTERNAL_PUSH_KEY}"
: "${VOICE_USER_ID:?Set VOICE_USER_ID to the same user_id used for shared history}"

RECORD_SECONDS="${RECORD_SECONDS:-5}"
TMP_DIR="${TMPDIR:-/tmp}/line-ai-speaker"
mkdir -p "$TMP_DIR"
AUDIO_FILE="$TMP_DIR/input.m4a"
REPLY_FILE="$TMP_DIR/reply.mp3"
TRANSCRIBE_JSON="$TMP_DIR/transcribe.json"
RESPONSE_JSON="$TMP_DIR/response.json"

cleanup() {
  rm -f "$AUDIO_FILE" "$REPLY_FILE" "$TRANSCRIBE_JSON" "$RESPONSE_JSON"
}
trap cleanup EXIT

command -v ffmpeg >/dev/null 2>&1 || { echo "ffmpeg is required (brew install ffmpeg)" >&2; exit 1; }
command -v afplay >/dev/null 2>&1 || { echo "afplay is required (macOS)" >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "curl is required" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 1; }

BASE="${VOICE_SERVER_BASE_URL%/}"
AUTH_HEADER="X-Internal-Key: ${INTERNAL_PUSH_KEY}"

echo "🎙️ ${RECORD_SECONDS}秒間、話してください..."
ffmpeg -hide_banner -loglevel error \
  -f avfoundation -i ":0" -t "$RECORD_SECONDS" \
  -ac 1 -ar 16000 -y "$AUDIO_FILE"

echo "🧠 音声を認識中..."
curl --fail-with-body -sS \
  -H "$AUTH_HEADER" \
  -F "file=@${AUDIO_FILE};type=audio/mp4" \
  "$BASE/api/voice/transcribe" > "$TRANSCRIBE_JSON"

TEXT="$(python3 - "$TRANSCRIBE_JSON" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
if not payload.get("ok"):
    raise SystemExit(payload.get("error", "transcription failed"))
print(str(payload.get("text", "")).strip())
PY
)"

if [[ -z "$TEXT" ]]; then
  echo "音声を認識できませんでした。"
  exit 0
fi

echo "👤 $TEXT"
echo "🤖 AI Secretaryに問い合わせ中..."
printf '%s' "$(python3 - "$VOICE_USER_ID" "$TEXT" <<'PY'
import json, sys
print(json.dumps({"user_id": sys.argv[1], "message": sys.argv[2]}, ensure_ascii=False))
PY
)" | curl --fail-with-body -sS \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  --data-binary @- \
  "$BASE/api/voice" > "$RESPONSE_JSON"

REPLY="$(python3 - "$RESPONSE_JSON" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
if not payload.get("ok"):
    raise SystemExit(payload.get("error", "voice request failed"))
print(str(payload.get("reply", "")).strip())
PY
)"

echo "🤖 $REPLY"
echo "🔊 読み上げ中..."
printf '%s' "$(python3 - "$REPLY" <<'PY'
import json, sys
print(json.dumps({"text": sys.argv[1]}, ensure_ascii=False))
PY
)" | curl --fail-with-body -sS \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  --data-binary @- \
  "$BASE/api/voice/speak" -o "$REPLY_FILE"

afplay "$REPLY_FILE"
