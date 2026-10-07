# UHIP Phase 0: Mac local camera

This is a **local-only** smoke test. It never calls LINE, a browser, a shell action, or a remote API.

## 1. Install the isolated camera dependencies

From the repository root:

```bash
python3 -m venv .venv-uhip
source .venv-uhip/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-uhip-mac.txt
```

The camera stack is deliberately separate from `requirements.txt` so the LINE/Render service does not install camera dependencies.

## 2. Download the official Gesture Recognizer model

The official MediaPipe Gesture Recognizer model bundle is available from Google:

```
https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task
```

Save it locally, for example:

```bash
mkdir -p .uhip-models
curl -L 'https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task'   -o .uhip-models/gesture_recognizer.task
```

The runner requires an explicit SHA-256 so a different local model cannot silently replace the expected model:

```bash
MODEL_SHA256="$(shasum -a 256 .uhip-models/gesture_recognizer.task | awk '{print $1}')"
echo "$MODEL_SHA256"
```

## 3. Run a bounded camera smoke test

The default limit is 120 frames. No frames are saved.

```bash
python scripts/run_uhip_local_camera.py   --model .uhip-models/gesture_recognizer.task   --model-sha256 "$MODEL_SHA256"   --max-frames 120
```

macOS may request camera permission. Denial or camera-open failure stops the run; it does not fall through to another device.

## Safety boundary

The current stock model is mapped only to:

- `Thumb_Up` -> `thumb_up`
- `Open_Palm` -> `open_palm`
- `Closed_Fist` -> `fist`

Other categories are converted to the internal `unknown` result and fail closed. Swipe and pinch are intentionally not enabled by the stock model yet.

Every classifier result passes the existing UHIP Recognition Gate before a Universal Event is produced. The gate still rejects low confidence, unstable tracking, multiple hands, out-of-frame input, and non-allowlisted gestures.

This phase does not execute any OS action and does not send camera data over the network.
