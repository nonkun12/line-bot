# RAG semantic retrieval evaluation plan

## Status

- Current production retriever: dependency-free SQLite keyword search.
- Current benchmark: offline-only, 8 documents and 7 queries; it is a smoke-test corpus, not a statistically representative quality claim.
- Semantic retrieval: NOT implemented and NOT enabled in the Distributed Loop.
- This document defines an evaluation gate only. It does not authorize runtime rollout.

## Candidate for local-only evaluation

Candidate checkpoint: `mlx-community/multilingual-e5-small-mlx`.

Reasons to evaluate:

- MIT-licensed model card and MLX checkpoint.
- 94-language multilingual model family, including Japanese.
- MLX checkpoint is listed as 235 MB.
- The upstream E5 model uses 384-dimensional embeddings.
- The upstream model card requires `query: ` prefixes for queries and `passage: ` prefixes for retrieved documents in asymmetric retrieval.

References:
- https://huggingface.co/mlx-community/multilingual-e5-small-mlx
- https://huggingface.co/intfloat/multilingual-e5-small

This is a candidate only. Runtime compatibility, latency, memory use, and retrieval quality must be measured on the target Mac before adoption. Do not assume MLX availability in CI.

## Evaluation sequence

1. Expand the offline corpus to at least 50 independently authored Japanese/English queries across exact terms, paraphrases, abbreviations, and negative/unrelated cases.
2. Freeze document IDs, relevant-document labels, and benchmark version before comparing retrievers.
3. Run the current SQLite keyword baseline and save metrics.
4. Run the candidate embedder locally with network access disabled after model acquisition; cache embeddings locally and use cosine similarity.
5. Compare keyword-only, vector-only, and hybrid retrieval using the same corpus and labels.
6. Report Recall@5, MRR@5, Precision@5, paraphrase Recall@5, exact-match Recall@5, latency, peak memory, and model/cache footprint.
7. Include negative queries and verify that irrelevant documents do not crowd out relevant results.

## Adoption gate

Do not enable semantic retrieval in the Distributed Loop unless all conditions are met:

- At least 50 labeled queries, including at least 20 paraphrase/cross-language cases and 10 negative cases.
- Hybrid Recall@5 improves by at least 10 percentage points overall and 20 percentage points on paraphrase cases over the keyword baseline.
- Exact-match Recall@5 does not regress.
- Precision@5 does not regress by more than 2 percentage points.
- Local latency and peak memory are measured and fit the target Mac's available resources.
- Model files and inference remain local; no hosted inference, telemetry, paid API, or automatic cloud fallback.
- Retrieval errors fall back to existing keyword search only; they must never change STOP/HOLD/REA status or authorize actions.
- Retrieved content remains bounded, namespace-isolated, sanitized, and explicitly advisory. Treat retrieved documents as untrusted data, never as instructions.

## Safety and rollout

- Keep semantic retrieval behind an explicit opt-in flag, default OFF.
- Keep current keyword retrieval as the baseline and safe fallback.
- Do not alter REA outcomes, approval gates, patch permissions, STOP/HOLD behavior, merge, or deployment.
- Do not download model weights in CI.
- Keep the PR Draft until the benchmark is representative and the local candidate has been measured.
