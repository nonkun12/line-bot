
def collect_memory_hint(error_text):
    """
    Phase 1.7 Memory Collector

    read_only only

    現在は過去情報検索の準備段階。
    """

    return {
        "has_memory": False,
        "matches": [],
        "query": error_text
    }


def search_memory(query):
    """
    Phase 1.8 Memory Search

    read_only only

    現在は検索口のみ。
    """

    return []
