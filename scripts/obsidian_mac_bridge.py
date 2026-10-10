"""Mac-local Obsidian bridge.

Run this process only on a trusted Mac where the Obsidian vault exists.
The bridge makes outbound HTTPS requests to the server; it does not open an
inbound port and never exposes the vault itself.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import sys
import time
import unicodedata
from urllib.parse import urlparse

import httpx

from agents.obsidian.node import obsidian_agent_node
from agents.obsidian.intents import normalize_obsidian_command


POLL_SECONDS = 5.0
REQUEST_TIMEOUT_SECONDS = 10.0
_WRITE_COMMAND_RE = re.compile(
    r"^obsidian\s*(?:に|へ)\s*(?:保存|記録|追記|追加)\b", re.IGNORECASE
)


class BridgeFailure(RuntimeError):
    """A safe, structured bridge failure without request or job contents."""

    def __init__(
        self,
        category: str,
        *,
        operation: str = "",
        status: int | None = None,
        exception: str = "",
        reason: str = "",
    ) -> None:
        super().__init__(category)
        self.category = category
        self.operation = operation
        self.status = status
        self.exception = exception
        self.reason = reason


def _emit_diagnostic(
    category: str,
    *,
    operation: str = "",
    status: int | None = None,
    exception: str = "",
    reason: str = "",
    outcome: str = "",
) -> None:
    """Write only allowlisted diagnostic fields; never include messages or values."""
    record: dict[str, object] = {
        "component": "obsidian_bridge",
        "run_id": os.environ.get("OBSIDIAN_BRIDGE_RUN_ID", ""),
        "category": category,
    }
    if operation:
        record["operation"] = operation
    if isinstance(status, int) and not isinstance(status, bool):
        record["status"] = status
    if exception and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", exception):
        record["exception"] = exception
    if reason:
        record["reason"] = reason
    if outcome:
        record["outcome"] = outcome
    print(
        "OBSIDIAN_BRIDGE_DIAGNOSTIC "
        + json.dumps(record, separators=(",", ":")),
        file=sys.stderr,
        flush=True,
    )


def _post_json(
    client: httpx.Client,
    url: str,
    *,
    operation: str,
    headers: dict[str, str],
    json_body: dict[str, object],
) -> object:
    try:
        response = client.post(url, headers=headers, json=json_body)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise BridgeFailure(
            "render_http_error",
            operation=operation,
            status=exc.response.status_code,
            exception=type(exc).__name__,
        ) from None
    except httpx.HTTPError as exc:
        raise BridgeFailure(
            "render_api_failure",
            operation=operation,
            exception=type(exc).__name__,
        ) from None
    try:
        return response.json()
    except Exception as exc:
        reason = "invalid_json"
        category = "job_fetch_failed" if operation == "claim" else "render_response_invalid"
        raise BridgeFailure(
            category, operation=operation, exception=type(exc).__name__, reason=reason
        ) from None


def _is_write_job(job: dict[str, object]) -> bool:
    message = job.get("message")
    if not isinstance(message, str):
        return False
    try:
        normalized = normalize_obsidian_command(
            unicodedata.normalize("NFKC", message).strip()
        )
    except Exception:
        return False
    return bool(normalized and _WRITE_COMMAND_RE.match(normalized))


def _local_failure_diagnostic(
    job: dict[str, object], result: dict[str, object]
) -> tuple[str, str]:
    reason = result.get("reason")
    allowed_reasons = {
        "invalid_local_agent_result",
        "vault_not_configured",
        "intent_rejected",
        "content_too_large",
        "overwrite_blocked",
        "operation_rejected",
        "invalid_command",
    }
    safe_reason = (
        reason
        if isinstance(reason, str) and reason in allowed_reasons
        else "unspecified"
    )
    if _is_write_job(job) and safe_reason in {
        "vault_not_configured",
        "operation_rejected",
    }:
        return "vault_write_failed", safe_reason
    return "local_job_rejected", safe_reason


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


def _validate_server_url(server_url: str) -> None:
    """Allow HTTPS endpoints and HTTP endpoints on loopback only."""
    try:
        if (
            not isinstance(server_url, str)
            or not server_url
            or any(char.isspace() for char in server_url)
        ):
            raise ValueError
        parsed_url = urlparse(server_url)
        hostname = parsed_url.hostname
        # Accessing .port also detects malformed port values.
        parsed_url.port
    except (AttributeError, ValueError):
        raise ValueError(
            "server_url must be a valid HTTPS URL or localhost HTTP URL"
        ) from None

    valid_hostname = False
    if hostname and not any(char.isspace() for char in hostname):
        try:
            ipaddress.ip_address(hostname)
            valid_hostname = True
        except ValueError:
            try:
                ascii_hostname = hostname.encode("idna").decode("ascii")
                labels = ascii_hostname.rstrip(".").split(".")
                valid_hostname = all(
                    label
                    and len(label) <= 63
                    and label[0].isalnum()
                    and label[-1].isalnum()
                    and all(char.isalnum() or char == "-" for char in label)
                    for label in labels
                )
            except UnicodeError:
                valid_hostname = False

    has_credentials = parsed_url.username is not None or parsed_url.password is not None
    if has_credentials:
        valid_hostname = False
    is_https = parsed_url.scheme == "https" and valid_hostname
    is_localhost = (
        parsed_url.scheme == "http"
        and hostname in {"localhost", "127.0.0.1"}
        and not has_credentials
    )
    if not (is_https or is_localhost):
        raise ValueError("server_url must use HTTPS unless targeting localhost")


def run_bridge(
    server_url: str,
    bridge_key: str,
    vault_path: str,
    poll_seconds: float = POLL_SECONDS,
    watch: bool = False,
) -> None:
    """Claim and execute jobs; one-shot by default, continuous polling only with watch=True."""
    _validate_server_url(server_url)
    if not isinstance(bridge_key, str) or not bridge_key.strip():
        raise ValueError("bridge_key is required")
    if not isinstance(vault_path, str) or not os.path.isdir(os.path.expanduser(vault_path)):
        raise ValueError("vault_path must be an existing directory")
    if not isinstance(poll_seconds, (int, float)) or not 1.0 <= poll_seconds <= 60.0:
        raise ValueError("poll_seconds must be between 1 and 60")

    base_url = server_url.rstrip("/")
    headers = _headers(bridge_key)

    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=False) as client:
        while True:
            try:
                payload = _post_json(
                    client,
                    f"{base_url}/api/obsidian/claim",
                    operation="claim",
                    headers=headers,
                    json_body={},
                )
                if not isinstance(payload, dict):
                    raise BridgeFailure(
                        "job_fetch_failed", operation="claim", reason="invalid_response"
                    )
                job = payload.get("job")
                if job is None:
                    _emit_diagnostic("job_not_available")
                    if not watch:
                        return
                    time.sleep(poll_seconds)
                    continue
                if not isinstance(job, dict):
                    raise BridgeFailure(
                        "job_fetch_failed", operation="claim", reason="invalid_job"
                    )

                job_id = job.get("id")
                claim_token = job.get("claim_token")
                if (
                    not isinstance(job_id, int)
                    or isinstance(job_id, bool)
                    or job_id <= 0
                    or not isinstance(claim_token, str)
                    or not claim_token.strip()
                ):
                    raise BridgeFailure(
                        "job_fetch_failed",
                        operation="claim",
                        reason="invalid_job_claim",
                    )

                execution_exception = False
                diagnostic_category = None
                diagnostic_detail = None
                try:
                    result = execute_local_job(job, vault_path)
                except Exception as exc:
                    execution_exception = True
                    diagnostic_category = (
                        "vault_write_failed" if _is_write_job(job) else "local_job_failed"
                    )
                    diagnostic_detail = type(exc).__name__
                    _emit_diagnostic(diagnostic_category, exception=diagnostic_detail)
                    result = {
                        "success": False,
                        "reply": "Mac側のObsidian処理を停止しました。",
                        "error": f"local operation failed ({diagnostic_detail})",
                    }

                if result.get("success") is not True and not execution_exception:
                    diagnostic_category, diagnostic_detail = _local_failure_diagnostic(job, result)
                    _emit_diagnostic(diagnostic_category, reason=diagnostic_detail)

                complete_payload = {
                    "job_id": job_id,
                    "claim_token": claim_token,
                    "success": result.get("success") is True,
                    "reply": str(result.get("reply", ""))[:20000],
                    "error": str(result.get("error", ""))[:2000] or None,
                }
                if diagnostic_category is not None:
                    # Send only allowlisted category/class or reason code.
                    # Raw exception messages and Obsidian note contents stay local.
                    complete_payload["diagnostic_category"] = diagnostic_category
                    complete_payload["diagnostic_detail"] = diagnostic_detail
                completed_payload = _post_json(
                    client,
                    f"{base_url}/api/obsidian/complete",
                    operation="complete",
                    headers=headers,
                    json_body=complete_payload,
                )
                expected_status = "completed" if complete_payload["success"] else "failed"
                if (
                    not isinstance(completed_payload, dict)
                    or completed_payload.get("ok") is not True
                    or completed_payload.get("status") != expected_status
                ):
                    # HTTP 200 alone is not evidence that the server completed the job.
                    raise BridgeFailure(
                        "render_response_invalid",
                        operation="complete",
                        reason="invalid_completion_result",
                    )

                _emit_diagnostic(
                    "job_completed",
                    outcome="success" if complete_payload["success"] else "failure",
                )
                if not watch:
                    return
            except BridgeFailure as exc:
                _emit_diagnostic(
                    exc.category,
                    operation=exc.operation,
                    status=exc.status,
                    exception=exc.exception,
                    reason=exc.reason,
                )
                if not watch:
                    raise
                time.sleep(poll_seconds)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                _emit_diagnostic(
                    "internal_bridge_failure", exception=type(exc).__name__
                )
                if not watch:
                    raise
                time.sleep(poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mac-local Obsidian bridge")
    parser.add_argument(
        "--server-url", default=os.environ.get("OBSIDIAN_BRIDGE_SERVER_URL", "")
    )
    parser.add_argument(
        "--bridge-key", default=os.environ.get("OBSIDIAN_BRIDGE_KEY", "")
    )
    parser.add_argument("--vault", default=os.environ.get("OBSIDIAN_VAULT_PATH", ""))
    parser.add_argument("--poll-seconds", type=float, default=POLL_SECONDS)
    parser.add_argument(
        "--watch", action="store_true",
        help="Keep polling continuously; default is one-shot.",
    )
    args = parser.parse_args()

    try:
        _validate_server_url(args.server_url)
        run_bridge(args.server_url, args.bridge_key, args.vault, args.poll_seconds, args.watch)
    except KeyboardInterrupt:
        _emit_diagnostic("bridge_interrupted")
        return 0
    except BridgeFailure:
        return 2
    except httpx.HTTPError as exc:
        _emit_diagnostic(
            "render_api_failure", operation="client_setup", exception=type(exc).__name__
        )
        return 2
    except ValueError as exc:
        _emit_diagnostic("configuration_error", exception=type(exc).__name__)
        return 2
    except Exception as exc:
        _emit_diagnostic("internal_bridge_failure", exception=type(exc).__name__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
