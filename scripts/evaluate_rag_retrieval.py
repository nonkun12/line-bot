"""Measure the dependency-free SQLite RAG baseline against a fixed corpus.

This is an offline evaluation utility. It never changes runtime retrieval policy.
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from rag_store import RagStore

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rag_retrieval_eval.json"


def evaluate(*, k: int = 5) -> dict:
    if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= 20:
        raise ValueError("k must be an integer from 1 to 20")
    corpus = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if corpus.get("schema_version") != 1:
        raise ValueError("unsupported retrieval fixture schema")

    with TemporaryDirectory(prefix="rag-eval-") as temp:
        store = RagStore(Path(temp) / "eval.sqlite3")
        for document in corpus["documents"]:
            store.add_document(
                namespace="rag-evaluation",
                source="fixture",
                source_id=document["id"],
                title=document["title"],
                content=document["content"],
            )

        rows = []
        for case in corpus["queries"]:
            matches = store.search(
                namespace="rag-evaluation", query=case["query"], limit=k
            )
            ranked_ids = [item["source_id"] for item in matches]
            relevant = set(case["relevant"])
            hits = [index for index, item_id in enumerate(ranked_ids, start=1)
                    if item_id in relevant]
            rows.append({
                "id": case["id"],
                "kind": case["kind"],
                "hit": bool(hits),
                "reciprocal_rank": 1.0 / hits[0] if hits else 0.0,
                "precision_at_k": len(set(ranked_ids) & relevant) / k,
                "recall_at_k": len(set(ranked_ids) & relevant) / len(relevant),
                "retrieved": ranked_ids,
            })

    count = len(rows)
    exact = [row for row in rows if row["kind"] == "exact"]
    paraphrase = [row for row in rows if row["kind"] == "paraphrase"]

    def average(items, key):
        return round(sum(row[key] for row in items) / len(items), 4) if items else 0.0

    return {
        "schema_version": 1,
        "retriever": "sqlite_keyword_baseline",
        "k": k,
        "query_count": count,
        "recall_at_k": average(rows, "recall_at_k"),
        "mrr_at_k": average(rows, "reciprocal_rank"),
        "precision_at_k": average(rows, "precision_at_k"),
        "exact_recall_at_k": average(exact, "recall_at_k"),
        "paraphrase_recall_at_k": average(paraphrase, "recall_at_k"),
        "cases": rows,
        "note": "Offline fixture score only; not production telemetry or proof of runtime RAG usage.",
    }


def main() -> None:
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
