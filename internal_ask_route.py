from flask import jsonify, request


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

        try:
            reply = generate_reply_func(user_id, message)
        except Exception as exc:
            print("INTERNAL ASK ERROR:", exc)
            return jsonify({
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }), 500

        print("INTERNAL ASK SUCCESS:", repr(reply))
        return jsonify({"ok": True, "reply": str(reply or "")})

    return internal_ask
