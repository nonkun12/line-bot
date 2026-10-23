"""Guarded Microsoft Graph mail webhook for explicit development commands.

Configuration is opt-in. The route remains inert until all Graph credentials,
the webhook client-state secret, and the sender allowlist are configured.
"""
from __future__ import annotations

import hmac
import os
from html.parser import HTMLParser
import re
import sqlite3
from typing import Any

import httpx
from flask import jsonify, request

import db
from distributed_loop_trigger import request_distributed_loop

_GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
_SUBJECT_PREFIX = "[LINEBOT]"


def _allowed_senders() -> set[str]:
    return {
        item.strip().casefold()
        for item in os.environ.get("EMAIL_ALLOWED_SENDERS", "").split(",")
        if item.strip()
    }


def _graph_config() -> tuple[str, str, str, str] | None:
    values = (
        os.environ.get("M365_TENANT_ID", "").strip(),
        os.environ.get("M365_CLIENT_ID", "").strip(),
        os.environ.get("M365_CLIENT_SECRET", "").strip(),
        os.environ.get("M365_MAILBOX_USER", "").strip(),
    )
    return values if all(values) else None


class _VisibleTextParser(HTMLParser):
    """Extract visible text only; ignore active and hidden-content elements."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style", "head", "title", "svg"}:
            self._skip_depth += 1
        elif tag.casefold() in {"br", "p", "div", "li"} and not self._skip_depth:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "head", "title", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag.casefold() in {"p", "div", "li"} and not self._skip_depth:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def _plain_body(message: dict[str, Any]) -> str:
    body = message.get("body")
    if not isinstance(body, dict) or not isinstance(body.get("content"), str):
        return ""
    content = body["content"]
    if str(body.get("contentType", "")).casefold() == "html":
        parser = _VisibleTextParser()
        parser.feed(content[:20000])
        content = "".join(parser.parts)
    # Normalize whitespace without changing the command's wording.
    return re.sub(r"[\t\r ]+", " ", content).strip()


def _claim_message(message_id: str, sender: str) -> bool:
    """Atomically claim a Graph message ID to prevent webhook replay."""
    event_id = "m365:" + message_id[:450]
    with db.get_conn() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO processed_events(event_id, user_id, source) VALUES (?, ?, ?)",
            (event_id, sender, "m365"),
        )
        return cursor.rowcount == 1


def register_m365_mail_route(app) -> None:
    @app.route("/m365/notifications", methods=["GET", "POST"])
    def m365_notifications():
        # Microsoft Graph validates a webhook by supplying validationToken.
        validation_token = request.args.get("validationToken")
        if validation_token is not None:
            if len(validation_token) > 2048:
                return "invalid validation token", 400
            from flask import Response
            return Response(validation_token, status=200, content_type="text/plain; charset=utf-8")

        config = _graph_config()
        client_state = os.environ.get("M365_WEBHOOK_CLIENT_STATE", "")
        allowed = _allowed_senders()
        if not config or not client_state or not allowed:
            return jsonify({"ok": False, "error": "Microsoft 365 mail intake is not configured"}), 503

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
            return jsonify({"ok": False, "error": "invalid notification payload"}), 400

        tenant_id, client_id, client_secret, mailbox = config
        accepted = 0
        ignored = 0
        try:
            with httpx.Client(timeout=12.0) as client:
                token_response = client.post(
                    f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "scope": "https://graph.microsoft.com/.default",
                        "grant_type": "client_credentials",
                    },
                )
                token_response.raise_for_status()
                token = token_response.json().get("access_token")
                if not isinstance(token, str) or not token:
                    return jsonify({"ok": False, "error": "Microsoft token unavailable"}), 502
                headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

                for notification in payload["value"][:20]:
                    if not isinstance(notification, dict):
                        ignored += 1
                        continue
                    supplied_state = notification.get("clientState")
                    if not isinstance(supplied_state, str) or not hmac.compare_digest(supplied_state, client_state):
                        ignored += 1
                        continue
                    resource_data = notification.get("resourceData")
                    message_id = resource_data.get("id") if isinstance(resource_data, dict) else None
                    if not isinstance(message_id, str) or not message_id or len(message_id) > 450:
                        ignored += 1
                        continue

                    message_url = f"{_GRAPH_ROOT}/users/{mailbox}/messages/{message_id}"
                    response = client.get(
                        message_url,
                        params={"$select": "id,internetMessageId,subject,from,body,isRead"},
                        headers=headers,
                    )
                    if response.status_code == 404:
                        ignored += 1
                        continue
                    response.raise_for_status()
                    message = response.json()
                    sender_obj = message.get("from")
                    email_obj = sender_obj.get("emailAddress") if isinstance(sender_obj, dict) else None
                    sender = email_obj.get("address", "").strip().casefold() if isinstance(email_obj, dict) else ""
                    subject = message.get("subject")
                    body = _plain_body(message)
                    if sender not in allowed or not isinstance(subject, str) or not subject.startswith(_SUBJECT_PREFIX):
                        ignored += 1
                        continue
                    command = body.strip()
                    # Only explicit bounded loop/status commands are accepted; no arbitrary email prose.
                    if not command or len(command) > 300:
                        ignored += 1
                        continue
                    if not _claim_message(str(message.get("internetMessageId") or message_id), sender):
                        ignored += 1
                        continue
                    handled, result = request_distributed_loop(sender, command, authorized=True)
                    if not handled:
                        ignored += 1
                        continue
                    accepted += 1
                    app.logger.info("M365 command accepted sender=%s message_id=%s", sender, message_id[:12])
        except httpx.HTTPError:
            app.logger.exception("Microsoft Graph notification processing failed")
            return jsonify({"ok": False, "error": "Microsoft Graph request failed"}), 502
        except (ValueError, TypeError, KeyError):
            app.logger.exception("Microsoft Graph notification payload was malformed")
            return jsonify({"ok": False, "error": "invalid Microsoft Graph response"}), 502

        return jsonify({"ok": True, "accepted": accepted, "ignored": ignored}), 202
