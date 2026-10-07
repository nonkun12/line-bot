# UHIP Phase 0: Mac local camera

This is a **bounded local-only** smoke test. The repository code does not call LINE, a browser, a shell action, or a remote API.

## 1. Install the isolated camera dependencies

From the repository root:

```bash
python3 -m venv .venv-uhip
source .venv-uhip/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-uhip-mac.txt
```

The camera stack is deliberately separate from `requirements.txt` so the LINE/Render service does not install camera dependencies.

## 2. Run the bounded camera smoke test

The default limit is 120 frames. Camera frames are processed in memory and are not saved.

```bash
python scripts/run_uhip_local_camera.py --max-frames 120
```

macOS may request camera permission. Denial or camera-open failure stops the run; it does not fall through to another device.

## Safety boundary

The local adapter uses MediaPipe's **Hands solution API**, not the MediaPipe Tasks API. The current MediaPipe privacy notice documents a Tasks-specific metrics channel to Google, so the distributed LINE service does not use that API.

The built-in deterministic geometry classifier only recognizes:

- `thumb_up`
- `open_palm`
- `fist`

Other shapes become the internal `unknown` result and fail closed. Swipe and pinch are intentionally not enabled yet.

Every classifier result passes the existing UHIP Recognition Gate before a Universal Event is produced. The Gate still rejects low confidence, unstable tracking, multiple hands, out-of-frame input, and non-allowlisted gestures.

The classifier does not authorize actions. It only produces a local observation. This phase does not execute any OS action and does not send camera frames over the network.

### Important

The MediaPipe package itself is third-party software. The project code does not make network calls, but a strict no-network validation should still be performed on the Mac with the local firewall/network monitor before treating this as a final zero-egress component.
