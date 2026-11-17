"""Measure the SQLite keyword RAG baseline against a fixed offline corpus."""
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
    if corpus.get("schema_version") != 2:
        raise ValueError("unsupported retrieval fixture schema")
    with TemporaryDirectory(prefix="rag-eval-") as temp:
        store = RagStore(Path(temp) / "eval.sqlite3")
        for document in corpus["documents"]:
            store.add_document(namespace="rag-evaluation", source="fixture",
                source_id=document["id"], title=document["title"], content=document["content"])
        rows = []
        for case in corpus["queries"]:
            matches = store.search(namespace="rag-evaluation", query=case["query"], limit=k)
            ranked_ids = [item["source_id"] for item in matches]
            relevant = set(case["relevant"])
            retrieved_relevant = len(set(ranked_ids) & relevant)
            if relevant:
                recall = retrieved_relevant / len(relevant)
                precision = retrieved_relevant / k
                reciprocal_rank = next((1.0 / index for index, item_id in enumerate(ranked_ids, 1)
                                        if item_id in relevant), 0.0)
                false_positive = False
            else:
                recall = None
                precision = None
                reciprocal_rank = None
                false_positive = bool(ranked_ids)
            rows.append({"id": case["id"], "kind": case["kind"], "hit": bool(retrieved_relevant),
                "recall_at_k": recall, "precision_at_k": precision,
                "reciprocal_rank": reciprocal_rank, "false_positive": false_positive,
                "retrieved": ranked_ids})
    def average(items, key):
        values = [row[key] for row in items if row[key] is not None]
        return round(sum(values) / len(values), 4) if values else 0.0
    positives = [row for row in rows if row["kind"] != "negative"]
    exact = [row for row in rows if row["kind"] == "exact"]
    paraphrase = [row for row in rows if row["kind"] == "paraphrase"]
    negatives = [row for row in rows if row["kind"] == "negative"]
    return {"schema_version": 2, "retriever": "sqlite_keyword_baseline", "k": k,
        "document_count": len(corpus["documents"]), "query_count": len(rows),
        "positive_query_count": len(positives), "negative_query_count": len(negatives),
        "recall_at_k": average(positives, "recall_at_k"),
        "mrr_at_k": average(positives, "reciprocal_rank"),
        "precision_at_k": average(positives, "precision_at_k"),
        "exact_recall_at_k": average(exact, "recall_at_k"),
        "paraphrase_recall_at_k": average(paraphrase, "recall_at_k"),
        "negative_false_positive_rate": average(negatives, "false_positive"),
        "cases": rows,
        "note": "Synthetic offline fixture only; not production telemetry or proof of runtime RAG use."}


def main() -> None:
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
