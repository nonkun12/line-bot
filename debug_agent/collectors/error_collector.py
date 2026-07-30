
def collect_error(error_text):
    """
    Phase 1.6 Error Collector

    read_only only
    """

    text = error_text or ""

    return {
        "raw_error": text,
        "length": len(text),
        "has_traceback": "traceback" in text.lower()
    }
