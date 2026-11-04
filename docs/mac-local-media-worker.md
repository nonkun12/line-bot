# Mac local audiovisual Goal worker

The worker is opt-in and runs exactly one claim attempt by default. It does not
install a LaunchAgent, run at login, or poll continuously unless `--loop` is
explicitly supplied.

## 1. Store the internal key in macOS Keychain

Use **Keychain Access** (no terminal command containing the secret):

1. Open Keychain Access and select the **login** keychain.
2. Create a new **Password** / **Generic Password** item.
3. Set **Item Name** to `line-bot-mac-media-worker`.
4. Set **Account** to `INTERNAL_PUSH_KEY`.
5. Paste the current Render `INTERNAL_PUSH_KEY` into the password field and save.

The worker reads only that exact item using the macOS `security find-generic-password`
command. It never invokes a shell to retrieve the value and never prints the secret.
An `INTERNAL_PUSH_KEY` environment variable, if explicitly supplied, takes precedence.
Do not put the key in this repository, a script, a command-line argument, or shell history.

If the key has not been confirmed in Keychain, do not run the worker. A missing or
short key causes a fail-closed exit before any JOB is claimed.

## 2. Configure the non-secret local settings

In Terminal, set the HTTPS service origin and a dedicated local output folder:

```bash
export LINE_BOT_BASE_URL="https://line-bot-yvea.onrender.com"
export LOCAL_MEDIA_OUTPUT_ROOT="$HOME/Movies/LINE-AI-Media"
```

The output folder is local to this Mac. Ensure it has enough free disk space.
No external asset download or publication is performed.

## 3. Run one claim attempt

From the repository root:

```bash
python3 scripts/mac_local_media_worker.py
```

One run claims at most one explicitly typed `mac_local_media.v1` Goal child job.
If no eligible job exists, it exits without doing work. Generation errors are reported
as HOLD; if the server cannot receive the HOLD report, the server-side claim lease
expires safely. Continuous polling is intentionally not enabled by default.

## Output contract

The current first draft produces scenario JSON, an editable storyboard, a shot list,
a music plan, original MIDI, a synthesized WAV preview, an edit decision list,
and a hash-verified executor receipt. The storyboard and shot list are included
in the receipt's artifact hashes and are not rendered image/video files.
The default Goal worker does **not** render an MP4. An explicit local Python call
to `create_audiovisual_production_bundle(..., render_animatic=True)` can opt into
Blender-generated procedural storyboard blocking frames followed by FFmpeg MP4
assembly. This is a first animatic made from abstract composition placeholders,
not final character animation, a finished cinematic scene, or rights-cleared footage.
The standard Mac Goal worker does not enable this option automatically; the
Blender/FFmpeg output needs separate local review before it is accepted.
