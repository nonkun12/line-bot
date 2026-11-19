"""n8n/internal AI request helper.

This module intentionally contains no Flask route registration.  It is a small,
reusable wrapper around the existing generate_reply() function so the existing
LINE webhook behavior is untouched.
"""


def handle_internal_ask(user_id, message, generate_reply_func):
    """Run the existing AI/LangGraph pipeline and return its reply text."""
    if not user_id:
        raise ValueError("user_id is required")
    if not message:
        raise ValueError("message is required")

    reply = generate_reply_func(user_id, message)
    if reply is None:
        reply = ""
    return str(reply)
