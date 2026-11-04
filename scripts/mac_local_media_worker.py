"""Opt-in Mac client for the typed local audiovisual Goal executor.

Run once by default. Continuous polling requires the explicit --loop flag.
No LaunchAgent or background service is installed by this script.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

# Allow direct execution as `python scripts/mac_local_media_worker.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.media.local_executor import execute_local_media_job

DEFAULT_INTERVAL_SECONDS = 30
MAX_INTERVAL_SECONDS = 300


class WorkerError(RuntimeError):
    pass


KEYCHAIN_SERVICE = "line-bot-mac-media-worker"
KEYCHAIN_ACCOUNT = "INTERNAL_PUSH_KEY"


def _read_keychain_secret() -> str:
    """Read one fixed Generic Password item; never invoke a shell or log its value."""
    if sys.platform != "darwin":
        return ""
    try:
        result = subprocess.run(
            [
                "/usr/bin/security", "find-generic-password",
                "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def _configuration() -> tuple[str, str]:
    base_url = os.environ.get("LINE_BOT_BASE_URL", "").strip().rstrip("/")
    internal_key = os.environ.get("INTERNAL_PUSH_KEY", "").strip()
    if not internal_key:
        internal_key = _read_keychain_secret()
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
        raise WorkerError("LINE_BOT_BASE_URL must be an HTTPS origin")
    if not internal_key or len(internal_key) < 24:
        raise WorkerError(
            "INTERNAL_PUSH_KEY is unavailable; add the Generic Password item "
            "line-bot-mac-media-worker / INTERNAL_PUSH_KEY in macOS Keychain"
        )
    output_root = os.environ.get("LOCAL_MEDIA_OUTPUT_ROOT", "").strip()
    if not output_root:
        raise WorkerError("LOCAL_MEDIA_OUTPUT_ROOT is missing; refusing to claim media work")
    return base_url, internal_key


def _request(base_url: str, internal_key: str, endpoint: str, payload: dict | None = None) -> dict:
    body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        base_url + endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-internal-key": internal_key,
            "User-Agent": "line-bot-mac-local-media-worker/1",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read(256 * 1024 + 1)
    except HTTPError as exc:
        detail = exc.read(2000).decode("utf-8", errors="replace")
        raise WorkerError(f"server returned HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise WorkerError(f"server request failed: {type(exc).__name__}") from exc
    if len(raw) > 256 * 1024:
        raise WorkerError("server response exceeded the size limit")
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkerError("server response was not valid JSON") from exc
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise WorkerError("server rejected the media worker request")
    return result


def run_once(base_url: str, internal_key: str) -> bool:
    render_setting = os.environ.get("LOCAL_MEDIA_RENDER_ANIMATIC", "0").strip()
    if render_setting not in {"0", "1"}:
        raise WorkerError("LOCAL_MEDIA_RENDER_ANIMATIC must be 0 or 1; refusing to claim work")
    render_animatic = render_setting == "1"
    claimed = _request(base_url, internal_key, "/internal/media-jobs/claim", {})
    if claimed.get("claimed") is not True:
        return False
    job = claimed.get("job")
    if not isinstance(job, dict) or job.get("job_type") != "goal_child":
        raise WorkerError("server returned an invalid claimed Goal job")
    job_id = job.get("id")
    claim_token = job.get("claim_token")
    payload = job.get("payload")
    if type(job_id) is not int or not isinstance(claim_token, str) or not isinstance(payload, dict):
        raise WorkerError("server returned an incomplete claim contract")

    try:
        output = execute_local_media_job(job, payload, render_animatic=render_animatic)
        _request(
            base_url,
            internal_key,
            "/internal/media-jobs/complete",
            {
                "job_id": job_id,
                "claim_token": claim_token,
                "result": output["result"],
                "evidence": output["evidence"],
            },
        )
        print(f"media Goal job {job_id}: completed (draft artifacts; animatic={render_animatic})")
    except Exception as exc:
        reason = f"{type(exc).__name__}: {str(exc)}"[:900]
        try:
            _request(
                base_url,
                internal_key,
                "/internal/media-jobs/hold",
                {"job_id": job_id, "claim_token": claim_token, "reason": reason},
            )
            print(f"media Goal job {job_id}: HOLD ({type(exc).__name__})", file=sys.stderr)
        except Exception as hold_exc:
            print(
                f"media Goal job {job_id}: HOLD report unavailable "
                f"({type(hold_exc).__name__}); claim lease will expire safely",
                file=sys.stderr,
            )
        return True
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the opt-in local audiovisual Goal worker")
    parser.add_argument(
        "--loop", action="store_true",
        help="poll continuously; omitted means exactly one poll",
    )
    parser.add_argument(
        "--interval", type=int, default=DEFAULT_INTERVAL_SECONDS,
        help=f"poll interval seconds when --loop is used (1-{MAX_INTERVAL_SECONDS})",
    )
    args = parser.parse_args()
    if not 1 <= args.interval <= MAX_INTERVAL_SECONDS:
        parser.error(f"--interval must be between 1 and {MAX_INTERVAL_SECONDS}")
    try:
        base_url, internal_key = _configuration()
    except WorkerError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        while True:
            try:
                did_work = run_once(base_url, internal_key)
                if not args.loop:
                    return 0
                if not did_work:
                    time.sleep(args.interval)
            except WorkerError as exc:
                print(str(exc), file=sys.stderr)
                if not args.loop:
                    return 1
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("local media worker stopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
