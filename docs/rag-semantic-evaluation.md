# RAG semantic retrieval evaluation plan

## Status

- Current production retriever: dependency-free SQLite keyword search.
- Current offline benchmark: 10 documents and 60 labeled queries (30 exact, 20 paraphrase, 10 negative), English and Japanese.
- The benchmark is synthetic and deterministic; it is not production telemetry or a statistically representative user-query sample.
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

1. Freeze document IDs, relevant-document labels, and benchmark version before comparing retrievers.
2. Run the current SQLite keyword baseline and retain the complete per-query result.
3. Run the candidate embedder locally with network access disabled after model acquisition; cache embeddings locally and use cosine similarity.
4. Compare keyword-only, vector-only, and hybrid retrieval using the same corpus and labels.
5. Report Recall@5, MRR@5, Precision@5, paraphrase Recall@5, exact-match Recall@5, negative false-positive rate, latency, peak memory, and model/cache footprint.
6. Add independently authored real task queries only after privacy review and explicit sanitization; never copy prompts, source code, diffs, file paths, credentials, or private user data into the fixture.

The current benchmark includes exact phrase and paraphrase coverage plus unrelated negative queries. Its scores are a baseline diagnostic, not a production quality claim. The keyword retriever's exact-match score is not assumed to be perfect; the test uses a regression floor.

## Adoption gate

Do not enable semantic retrieval in the Distributed Loop unless all conditions are met:

- At least 50 labeled queries, including at least 20 paraphrase/cross-language cases and 10 negative cases.
- Hybrid Recall@5 improves by at least 10 percentage points overall and 20 percentage points on paraphrase cases over the measured keyword baseline.
- Exact-match Recall@5 does not regress.
- Precision@5 does not regress by more than 2 percentage points.
- Negative false-positive rate is measured and does not worsen versus the keyword baseline.
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
