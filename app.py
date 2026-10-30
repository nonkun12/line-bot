
@app.route("/camera-test", methods=["GET"])
def camera_test():
    """Safe browser camera smoke-test page; no frames are uploaded or stored."""
    return render_template("camera_test.html")

client = _ai_client_client
generate_ai_secretary_report = generate_secretary_report

# LINE's per-message limit is 5,000 UTF-16 code units. Count supplementary-
# plane characters as two units so emoji cannot exceed the API limit.
LINE_MAX_MESSAGE_LENGTH = 5000
LINE_MAX_MESSAGES_PER_SEND = 5
LINE_MAX_TOTAL_LENGTH = LINE_MAX_MESSAGE_LENGTH * LINE_MAX_MESSAGES_PER_SEND
_LINE_TRUNCATION_NOTICE = "\n\n(※文字数が多いため一部を省略しました)"


def _line_text_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _take_line_text(value: str, limit: int) -> tuple[str, str]:
    """Split at a Unicode character boundary within a UTF-16 unit budget."""
    used = 0
    for index, char in enumerate(value):
        width = 2 if ord(char) > 0xFFFF else 1
        if used + width > limit:
            return value[:index], value[index:]
        used += width
    return value, ""


def _build_dashboard_url(user_id: str, path: str = "/dashboard") -> str:
    ts = int(time.time())
    secret = os.environ.get("DASHBOARD_LINK_SECRET") or os.environ.get("DASHBOARD_PASSWORD") or ""
    payload = f"{user_id}:{ts}"
    token = __import__("hmac").new(secret.encode(), payload.encode(), __import__("hashlib").sha256).hexdigest()
    query = urlencode({"user_id": user_id, "ts": ts, "token": token})
    return f"https://line-bot-yvea.onrender.com{path}?{query}"


def split_line_message(text, max_len=LINE_MAX_MESSAGE_LENGTH, max_messages=LINE_MAX_MESSAGES_PER_SEND, max_total=LINE_MAX_TOTAL_LENGTH):
    if not text:
        return [text or ""]
    truncated = False
    remaining = text
    if _line_text_length(remaining) > max_total:
        remaining, _ = _take_line_text(remaining, max_total)
        truncated = True

    chunks = []
    while remaining and len(chunks) < max_messages:
        chunk, rest = _take_line_text(remaining, max_len)
        if rest:
            # Prefer a nearby newline without exceeding the UTF-16 unit budget.
            split_at = chunk.rfind("\n")
            if split_at > 0:
                chunk, rest = chunk[:split_at + 1], chunk[split_at + 1:] + rest
        chunks.append(chunk)
        remaining = rest

    if remaining:
        truncated = True
    if not chunks:
        chunks = [""]
    if truncated:
        notice = _LINE_TRUNCATION_NOTICE
        last, _ = _take_line_text(chunks[-1], max(0, max_len - _line_text_length(notice)))
        chunks[-1] = last + notice
    return chunks


def _build_line_messages(text):
    return [TextMessage(text=chunk) for chunk in split_line_message(text)]


def _line_reply(reply_token, text):
    with StepTimer("line_out") as timer:
        try:
            with ApiClient(configuration) as api:
                MessagingApi(api).reply_message(
                    ReplyMessageRequest(reply_token=reply_token, messages=_build_line_messages(text))
                )
        except Exception as exc:
            timer.fail(error=exc, error_location="app._line_reply")
            raise
        timer.ok(http_status=200)


def _line_push(user_id, text):
    with StepTimer("line_out") as timer:
