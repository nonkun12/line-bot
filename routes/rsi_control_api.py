"""Dedicated Orca -> RSI control snapshot endpoint."""
from __future__ import annotations

import os
from dataclasses import asdict
from flask import Blueprint, current_app, jsonify

from core.rsi_orca_auth import make_signed_envelope, RSIControlTransportError

rsi_control_bp = Blueprint("rsi_control", __name__)


@rsi_control_bp.route("/internal/rsi/control", methods=["GET"])
def get_signed_rsi_control():
    """Publish only a trusted, explicitly injected control snapshot.

    The provider is installed by the Orca control-plane composition root as
    app.extensions["rsi_control_snapshot_provider"]. Missing provider or key
    fails closed; this endpoint never manufactures a permissive snapshot.
    """
    provider = current_app.extensions.get("rsi_control_snapshot_provider")
    secret = os.environ.get("RSI_CONTROL_HMAC_SECRET", "")
    if not callable(provider) or len(secret.encode("utf-8")) < 32:
        return jsonify({"ok": False, "error": "rsi_control_source_unavailable"}), 503
    try:
        snapshot = provider()
        envelope = make_signed_envelope(snapshot, secret)
        response = jsonify(envelope)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return response, 200
    except (RSIControlTransportError, TypeError, ValueError):
        current_app.logger.exception("ORCA RSI CONTROL SNAPSHOT REJECTED")
        return jsonify({"ok": False, "error": "rsi_control_snapshot_invalid"}), 503
    except Exception:
        current_app.logger.exception("ORCA RSI CONTROL PROVIDER ERROR")
        return jsonify({"ok": False, "error": "rsi_control_source_unavailable"}), 503
