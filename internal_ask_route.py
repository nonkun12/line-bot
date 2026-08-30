from flask import jsonify, request

from n8n_delegate import is_ai_app_builder_request, _call_ai_app_builder

try:
    from e2e_status import StepTimer
except Exception:  # 監視層が使えなくても既存動作に影響させない
    class StepTimer:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ok(self, *a, **k):
            pass

        def fail(self, *a, **k):
            pass


def register_internal_ask_route(app, internal_push_key, generate_reply_func):
    """Register /internal/ask without changing the existing LINE webhook."""

    @app.route("/internal/ask", methods=["POST"])
    def internal_ask():
        provided_key = request.headers.get("x-internal-key")
        if provided_key != internal_push_key:
            return jsonify({"ok": False, "error": "unauthorized"}), 401

        data = request.get_json(silent=True) or {}
        user_id = data.get("user_id")
        message = data.get("message")
        if not user_id or not message:
            return jsonify({
                "ok": False,
                "error": "user_id and message are required",
            }), 400

        # Explicit app-building requests use the existing App Builder classifier
        # and delegation code. The result is returned to n8n as `reply`; LINE
        # delivery remains the responsibility of the existing /internal/push node.
        if is_ai_app_builder_request(message):
            handled, reply_text = _call_ai_app_builder(user_id, message)
            if handled:
                print(f"[LOG] /internal/ask: routed to ai-app-builder user_id={user_id!r}")
                return jsonify({"ok": True, "reply": reply_text or ""})
            # AI_APP_BUILDER_URL未設定時のみ、既存のgenerate_reply_funcへフォールバックする。

        # AI/MCP呼び出しはgenerate_reply_func内部で行われるため、
        # /internal/ask と AI/MCP の2ステップとして記録する
        # (現状はほぼ同じ成否になるが、将来AI/MCP内部で個別計装しても
        #  この2重記録とは独立して追加できるようにしている)
        with StepTimer("internal_ask") as ask_timer, StepTimer("ai_mcp") as ai_timer:
            try:
                reply = generate_reply_func(user_id, message)
            except Exception as exc:
                print("INTERNAL ASK ERROR:", exc)
                ai_timer.fail(error=exc, error_location="generate_reply")
                ask_timer.fail(http_status=500, error=exc, error_location="internal_ask")
                return jsonify({
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }), 500

            ai_timer.ok()
            ask_timer.ok(http_status=200)

        print(f"[LOG] /internal/ask success: user_id={user_id!r}")
        return jsonify({"ok": True, "reply": str(reply or "")})

    return internal_ask