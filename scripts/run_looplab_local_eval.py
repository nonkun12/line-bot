"""Run a bounded, local-only RAG retrieval comparison for LoopLab.

The bundled corpus is synthetic/offline. Results are diagnostic only and are
never accepted as production LoopLab or RSI evidence. The challenger is a
loopback-only local model; no hosted API or cloud fallback is possible.
"""
from __future__ import annotations
import argparse, json, time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from core.local_model_client import LocalModelError, create_local_model_client_from_env
from rag_store import RagStore

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rag_retrieval_eval.json"
SYSTEM_PROMPT = (
    "You are a retrieval reranker. Select document IDs relevant to the query. "
    "Return only JSON: {\"ranked_ids\":[\"id\",...]}. Use only supplied IDs, "
    "do not invent IDs, and return at most 5 unique IDs. If none are relevant, return []."
)

def _metrics(rows: list[dict[str, Any]], k: int) -> dict[str, Any]:
    positives = [row for row in rows if row["relevant"]]
    negatives = [row for row in rows if not row["relevant"]]
    def avg(items, key):
        return round(sum(float(item[key]) for item in items) / len(items), 4) if items else 0.0
    exact = [row for row in positives if row["kind"] == "exact"]
    paraphrase = [row for row in positives if row["kind"] == "paraphrase"]
    return {"query_count": len(rows), "recall_at_k": avg(positives, "recall_at_k"),
            "precision_at_k": avg(positives, "precision_at_k"), "mrr_at_k": avg(positives, "reciprocal_rank"),
            "exact_recall_at_k": avg(exact, "recall_at_k"), "paraphrase_recall_at_k": avg(paraphrase, "recall_at_k"),
            "negative_false_positive_rate": avg(negatives, "false_positive")}

def _score(query_rows, ranked_by_id, k):
    scored = []
    for case in query_rows:
        ranked = ranked_by_id[case["id"]][:k]
        relevant = set(case["relevant"])
        hits = len(set(ranked) & relevant)
        rr = next((1.0 / i for i, doc_id in enumerate(ranked, 1) if doc_id in relevant), 0.0)
        scored.append({"id": case["id"], "kind": case["kind"], "relevant": bool(relevant), "retrieved": ranked,
            "recall_at_k": hits / len(relevant) if relevant else 0.0, "precision_at_k": hits / k if relevant else 0.0,
            "reciprocal_rank": rr if relevant else 0.0, "false_positive": bool(ranked) if not relevant else False})
    return scored

def _model_rank(client: Any, query: str, documents: list[dict[str, str]], k: int) -> list[str]:
    catalog = [{"id": d["id"], "title": d["title"], "content": d["content"][:1200]} for d in documents]
    response = client.chat.completions.create(model=client.model, messages=[
        {"role": "system", "content": SYSTEM_PROMPT.replace("at most 5", f"at most {k}")},
        {"role": "user", "content": json.dumps({"query": query, "documents": catalog}, ensure_ascii=False)}],
        temperature=0.0, max_completion_tokens=256, include_reasoning=False)
    content = response.choices[0].message.content.strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("challenger_response_not_json") from None
        try:
            parsed = json.loads(content[start:end + 1])
        except json.JSONDecodeError:
            raise ValueError("challenger_response_not_json") from None
    ranked = parsed.get("ranked_ids") if isinstance(parsed, dict) else None
    valid_ids = {d["id"] for d in documents}
    if not isinstance(ranked, list) or len(ranked) > k or any(not isinstance(x, str) or x not in valid_ids for x in ranked) or len(set(ranked)) != len(ranked):
        raise ValueError("challenger_ranked_ids_invalid")
    return ranked

def run(*, limit: int | None = None, k: int = 5, baseline_only: bool = False) -> dict[str, Any]:
    if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= 5:
        raise ValueError("k must be an integer from 1 to 5")
    corpus = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if corpus.get("schema_version") != 2 or not isinstance(corpus.get("documents"), list) or not isinstance(corpus.get("queries"), list):
        raise ValueError("benchmark_fixture_invalid")
    queries = corpus["queries"][:limit] if limit is not None else corpus["queries"]
    if not queries:
        raise ValueError("benchmark_query_set_empty")
    with TemporaryDirectory(prefix="looplab-local-eval-") as temp:
        store = RagStore(Path(temp) / "baseline.sqlite3")
        for d in corpus["documents"]:
            store.add_document(namespace="looplab-offline", source="synthetic-fixture", source_id=d["id"], title=d["title"], content=d["content"])
        baseline_ranked = {case["id"]: [item["source_id"] for item in store.search(namespace="looplab-offline", query=case["query"], limit=k)] for case in queries}
    baseline_rows = _score(queries, baseline_ranked, k)
    result = {"schema_version": 1, "status": "BASELINE_ONLY" if baseline_only else "BLOCKED",
        "benchmark": "synthetic_offline_rag_fixture_v2", "production_evidence": False,
        "rsi_ingestion": "PROHIBITED_SYNTHETIC_FIXTURE", "k": k, "sample_count": len(queries),
        "baseline": {"retriever": "sqlite_keyword_baseline", "metrics": _metrics(baseline_rows, k), "cases": baseline_rows},
        "challenger": None, "comparison": None,
        "safety": {"local_only": True, "hosted_api": False, "cloud_fallback": False, "execution_authorized": False}}
    if baseline_only:
        return result
    try:
        client = create_local_model_client_from_env()
        started = time.monotonic()
        challenger_ranked = {case["id"]: _model_rank(client, case["query"], corpus["documents"], k) for case in queries}
        elapsed = round(time.monotonic() - started, 3)
        challenger_rows = _score(queries, challenger_ranked, k)
        bm, cm = result["baseline"]["metrics"], _metrics(challenger_rows, k)
        result.update({"status": "COMPLETED_DIAGNOSTIC",
            "challenger": {"candidate_id": client.model, "provider": "loopback_local_model", "metrics": cm, "elapsed_seconds": elapsed, "cases": challenger_rows},
            "comparison": {"recall_at_k_delta": round(cm["recall_at_k"]-bm["recall_at_k"], 4),
                "paraphrase_recall_at_k_delta": round(cm["paraphrase_recall_at_k"]-bm["paraphrase_recall_at_k"], 4),
                "precision_at_k_delta": round(cm["precision_at_k"]-bm["precision_at_k"], 4),
                "negative_false_positive_rate_delta": round(cm["negative_false_positive_rate"]-bm["negative_false_positive_rate"], 4)}})
    except (LocalModelError, OSError, ValueError) as exc:
        result["reason"] = str(exc)[:160]
    return result

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Run only the first N queries (smoke test)")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--baseline-only", action="store_true")
    parser.add_argument("--output", default="artifacts/looplab-local-eval.json")
    args = parser.parse_args()
    if args.limit is not None and not 1 <= args.limit <= 60:
        parser.error("--limit must be between 1 and 60")
    result = run(limit=args.limit, k=args.k, baseline_only=args.baseline_only)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "sample_count": result["sample_count"],
        "baseline_recall_at_k": result["baseline"]["metrics"]["recall_at_k"],
        "challenger_recall_at_k": (result.get("challenger") or {}).get("metrics", {}).get("recall_at_k"),
        "output": str(output), "production_evidence": False, "rsi_ingestion": result["rsi_ingestion"],
        "reason": result.get("reason")}, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] in {"BASELINE_ONLY", "COMPLETED_DIAGNOSTIC"} else 2

if __name__ == "__main__":
    raise SystemExit(main())
