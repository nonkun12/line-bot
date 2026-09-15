# Mac AI Speaker

This client uses the existing channel-independent voice API. No server-side voice implementation is duplicated.

## Flow

`Mac microphone -> /api/voice/transcribe -> /api/voice -> /api/voice/speak -> afplay`

The AI response goes through the same AI Gateway / Core used by the other channels.

## Requirements

- macOS
- `ffmpeg` (`brew install ffmpeg`)
- `curl`
- `python3`
- macOS `afplay`

## Configuration

Set these environment variables in the Mac shell:

```bash
export VOICE_SERVER_BASE_URL="https://line-bot-yvea.onrender.com"
export INTERNAL_PUSH_KEY="<the same server-side internal key>"
export VOICE_USER_ID="<the same user_id used for the user's shared history>"
```

Do not commit the internal key to the repository.

## Run

```bash
chmod +x scripts/mac_speaker_client.sh
RECORD_SECONDS=5 ./scripts/mac_speaker_client.sh
```

The first run may require macOS permission for Terminal (or the calling app) to access the microphone.

## Safety

The script sends audio and text only to the configured `VOICE_SERVER_BASE_URL`. It does not store the API key in the repository. Temporary audio files are created under the system temporary directory and removed on exit.

## Current limitation

The first version records a fixed-length clip (`RECORD_SECONDS`). Wake-word detection, continuous listening, interruption/barge-in, and a menu-bar/GUI client are intentionally deferred until the basic end-to-end path is verified.
