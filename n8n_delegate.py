"""LINE -> n8n Webhook delegation helper.

This module intentionally contains no Flask route registration and no
retry/dedup logic. It is a small, fire-and-forget wrapper that posts the
incoming LINE message to an n8n Webhook so the existing LINE handling code
in app.py stays untouched aside from a single branch.
"""

import httpx


def _delegate_to_n8n(user_id, message, webhook_url, timeout=5):
    """n8n WebhookへLINEメッセージを送信する(fire-and-forget)。

    n8n側のworkflowがこの後、既存の /internal/ask や /internal/push を
    呼び出して実際の返信処理を行う想定のため、ここでは送信結果を
    待たずに例外も外へ伝播させない。
    """
    try:
        httpx.post(
            webhook_url,
            json={"user_id": user_id, "message": message},
            timeout=timeout,
        )
    except Exception as exc:
        print("N8N DELEGATE ERROR:", exc)
