"""Offline A/B benchmark for conservative synonym query expansion (no production changes)."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rag_retrieval_eval.json"

# Small, explicit vocabulary only. This is auditable lexical expansion, not semantic inference.
SYNONYM_GROUPS = (
    ("test", "tests", "testing", "unit test", "pytest", "regression"),
    ("failure", "fail", "failed", "broken", "error", "issue"),
    ("timeout", "timed out", "time budget", "deadline", "duration limit"),
    ("security", "secure", "sensitive", "credential", "authentication"),
    ("permission", "access right", "privilege", "authorization"),
    ("stop", "halt", "interrupt", "停止", "中断", "緊急停止"),
    ("hold", "held", "paused", "保留", "停止状態"),
    ("review", "reviewer", "inspect", "検証", "審査"),
    ("diff", "patch", "change", "modified", "差分", "変更"),
    ("queue", "pending work", "task list", "work items", "タスク"),
    ("memory", "persistent", "persistence", "保存", "永続"),
    ("model", "inference", "llm", "language model", "言語モデル"),
    ("local", "offline", "on device", "端末内", "ローカル"),
    ("secret", "token", "password", "private key", "api key", "認証情報"),
    ("approval", "approve", "consent", "human authorization", "承認"),
)

def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()

def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+|[ぁ-んァ-ン一-龥]{2,}", normalize(text)))

def expand(query: str) -> set[str]:
    normalized = normalize(query)
    query_tokens = tokens(query)
    expanded = set(query_tokens)
    for group in SYNONYM_GROUPS:
        if any(normalize(term) in normalized or tokens(term) & query_tokens for term in group):
            for term in group:
                expanded.update(tokens(term))
    return expanded

def rank(documents: list[dict], query: str, *, k: int = 5) -> list[str]:
    q = expand(query)
    scored = []
    for doc in documents:
        haystack = tokens(doc.get("title", "") + " " + doc.get("content", ""))
        score = len(q & haystack)
        scored.append((score, -len(scored), doc["id"]))
    scored.sort(reverse=True)
    return [doc_id for score, _, doc_id in scored if score > 0][:k]

def evaluate(*, k: int = 5) -> dict:
    if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= 20:
        raise ValueError("k must be an integer from 1 to 20")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if fixture.get("schema_version") != 2:
        raise ValueError("unsupported retrieval fixture schema")
    docs = fixture["documents"]
    rows = []
    for case in fixture["queries"]:
        found = rank(docs, case["query"], k=k)
        relevant = set(case["relevant"])
        if relevant:
            hit_count = len(set(found) & relevant)
            recall = hit_count / len(relevant)
            rr = next((1 / i for i, item in enumerate(found, 1) if item in relevant), 0.0)
            precision = hit_count / k
            false_positive = False
        else:
            recall = rr = precision = None
            false_positive = bool(found)
        rows.append({"id": case["id"], "kind": case["kind"], "retrieved": found,
                    "recall_at_k": recall, "precision_at_k": precision,
                    "mrr_at_k": rr, "false_positive": false_positive})
    def avg(group: list[dict], field: str) -> float:
        vals = [r[field] for r in group if r[field] is not None]
        return round(sum(vals) / len(vals), 4) if vals else 0.0
    positive = [r for r in rows if r["kind"] != "negative"]
    exact = [r for r in rows if r["kind"] == "exact"]
    paraphrase = [r for r in rows if r["kind"] == "paraphrase"]
    negative = [r for r in rows if r["kind"] == "negative"]
    return {"schema_version": 1, "method": "explicit_synonym_expansion_offline",
            "k": k, "document_count": len(docs), "query_count": len(rows),
            "recall_at_k": avg(positive, "recall_at_k"),
            "exact_recall_at_k": avg(exact, "recall_at_k"),
            "paraphrase_recall_at_k": avg(paraphrase, "recall_at_k"),
            "mrr_at_k": avg(positive, "mrr_at_k"),
            "precision_at_k": avg(positive, "precision_at_k"),
            "negative_false_positive_rate": avg(negative, "false_positive"),
            "cases": rows,
            "note": "Synthetic fixture only; expansion is explicit and may increase false positives. Production retriever unchanged."}

if __name__ == "__main__":
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
