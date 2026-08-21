"""LINE -> n8n Webhook delegation helper.

This module intentionally contains no Flask route registration and no
retry/dedup logic. It is a small, fire-and-forget wrapper that posts the
incoming LINE message to an n8n Webhook so the existing LINE handling code
in app.py stays untouched aside from a single branch.
"""

import time
import httpx

try:
    from e2e_status import record_step
except Exception:  # 監視層が使えなくても既存動作に影響させない
    def record_step(*args, **kwargs):
        pass


def _delegate_to_n8n(user_id, message, webhook_url, timeout=5):
    """n8n WebhookへLINEメッセージを送信する(fire-and-forget)。

    n8n側のworkflowがこの後、既存の /internal/ask や /internal/push を
    呼び出して実際の返信処理を行う想定のため、ここでは送信結果を
    待たずに例外も外へ伝播させない(この挙動は変更していない)。
    E2Eダッシュボード用に、結果だけ記録してから握りつぶす。
    """
    start = time.time()
    try:
        res = httpx.post(
            webhook_url,
            json={"user_id": user_id, "message": message},
            timeout=timeout,
        )
        elapsed_ms = int((time.time() - start) * 1000)
        ok = 200 <= res.status_code < 300
        record_step(
            "n8n_webhook", ok,
            http_status=res.status_code,
            response_time_ms=elapsed_ms,
            error=None if ok else f"n8n webhook returned {res.status_code}",
        )
    except Exception as exc:
        elapsed_ms = int((time.time() - start) * 1000)
        record_step(
            "n8n_webhook", False,
            response_time_ms=elapsed_ms,
            error=str(exc),
            error_location="_delegate_to_n8n",
        )
        print("N8N DELEGATE ERROR:", exc)
