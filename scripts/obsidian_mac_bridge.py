"""Mac-local Obsidian bridge.

Run this process only on a trusted Mac where the Obsidian vault exists.
The bridge makes outbound HTTPS requests to the server; it does not open an
inbound port and never exposes the vault itself.
"""
from __future__ import annotations

import argparse
import os
import time

import httpx

from agents.obsidian.node import obsidian_agent_node


POLL_SECONDS = 5.0
REQUEST_TIMEOUT_SECONDS = 10.0


def execute_local_job(job: dict[str, object], vault_path: str) -> dict[str, object]:
    """Execute one claimed command using the same guarded Obsidian Agent."""
    if not isinstance(job, dict):
        raise ValueError("job must be an object")
    message = job.get("message")
    user_id = job.get("user_id")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("job message is required")
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("job user_id is required")
    if not isinstance(vault_path, str) or not vault_path.strip():
        raise ValueError("vault_path is required")

    os.environ["OBSIDIAN_VAULT_PATH"] = os.path.expanduser(vault_path.strip())
    state = obsidian_agent_node(
        {
            "user_id": user_id,
            "raw_message": message,
            "channel": "obsidian_bridge",
            "metadata": {"bridge": "mac-local"},
            "agent_results": {},
        }
    )
    result = dict(state.get("agent_results", {}).get("obsidian", {}))
    text = result.get("text")
    success = result.get("success")
    if not isinstance(success, bool):
        success = False
        result["reason"] = "invalid_local_agent_result"
    result["success"] = success
    result["reply"] = text if isinstance(text, str) else ""
    return result


def _headers(bridge_key: str) -> dict[str, str]:
    return {"X-Obsidian-Bridge-Key": bridge_key}


def run_bridge(server_url: str, bridge_key: str, vault_path: str, poll_seconds: float = POLL_SECONDS, watch: bool = False) -> None:
    """Claim and execute jobs; one-shot by default, continuous polling only with watch=True."""
    if not server_url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise ValueError("server_url must use HTTPS unless targeting localhost")
    if not bridge_key.strip():
        raise ValueError("bridge_key is required")
    if not os.path.isdir(os.path.expanduser(vault_path)):
        raise ValueError("vault_path must be an existing directory")
    if not 1.0 <= poll_seconds <= 60.0:
        raise ValueError("poll_seconds must be between 1 and 60")

    base_url = server_url.rstrip("/")
    headers = _headers(bridge_key)

    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=False) as client:
        while True:
            try:
                response = client.post(
                    f"{base_url}/api/obsidian/claim",
                    headers=headers,
                    json={},
                )
                response.raise_for_status()
                payload = response.json()
                job = payload.get("job")
                if job is None:
                    if not watch:
                        print("[OBSIDIAN BRIDGE] no pending job; stopped")
                        return
                    time.sleep(poll_seconds)
                    continue

                job_id = job.get("id")
                claim_token = job.get("claim_token")
                if (
                    not isinstance(job_id, int)
                    or not isinstance(claim_token, str)
                    or not claim_token.strip()
                ):
                    raise RuntimeError("server returned an invalid Obsidian job claim")

                try:
                    result = execute_local_job(job, vault_path)
                except Exception as exc:
                    result = {
                        "success": False,
                        "reply": "Mac側のObsidian処理を停止しました。",
                        "error": f"{type(exc).__name__}: {exc}"[:2000],
                    }

                complete_payload = {
                    "job_id": job_id,
                    "claim_token": claim_token,
                    "success": bool(result.get("success", False)),
                    "reply": str(result.get("reply", ""))[:20000],
                    "error": str(result.get("error", ""))[:2000] or None,
                }
                completed = client.post(
                    f"{base_url}/api/obsidian/complete",
                    headers=headers,
                    json=complete_payload,
                )
                completed.raise_for_status()
                completed_payload = completed.json()
                print(
                    f"[OBSIDIAN BRIDGE] job={job_id} "
                    f"success={complete_payload['success']} "
                    f"server_status={completed_payload.get('status', 'unknown')}"
                )
                if not watch:
                    return
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                # Do not print request bodies or bridge secrets.
                print(f"[OBSIDIAN BRIDGE] stopped request cycle: {type(exc).__name__}")
                if not watch:
                    raise
                time.sleep(poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mac-local Obsidian bridge")
    parser.add_argument("--server-url", default=os.environ.get("OBSIDIAN_BRIDGE_SERVER_URL", ""))
    parser.add_argument("--bridge-key", default=os.environ.get("OBSIDIAN_BRIDGE_KEY", ""))
    parser.add_argument("--vault", default=os.environ.get("OBSIDIAN_VAULT_PATH", ""))
    parser.add_argument("--poll-seconds", type=float, default=POLL_SECONDS)
    parser.add_argument("--watch", action="store_true", help="Keep polling continuously; default is one-shot.")
    args = parser.parse_args()

    try:
        run_bridge(args.server_url, args.bridge_key, args.vault, args.poll_seconds, args.watch)
    except KeyboardInterrupt:
        print("[OBSIDIAN BRIDGE] stopped")
        return 0
    except Exception as exc:
        print(f"[OBSIDIAN BRIDGE] configuration error: {type(exc).__name__}: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
