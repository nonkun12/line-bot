# English Learning Agent

A local-first English-learning workflow with reviewed core-image vocabulary.

## Learner commands

- `単語`: show three locally reviewed words with core images and examples.
- `クイズ`: start a three-choice quiz from the reviewed vocabulary.
- `復習`: start a short review cycle.
- `コアイメージ inspect`: explain a reviewed word. Unknown words are not guessed.
- `単語追加: example`: submit a candidate for human review. Submission never publishes it to the learning lexicon.

## Local vocabulary review

Review is deliberately not exposed as a public LINE command or HTTP endpoint. It is available only through the local CLI, and only for reviewer IDs configured in the trusted runtime environment.

Configure the allowlist in the process environment:

```sh
export ENGLISH_VOCAB_REVIEWER_IDS="reviewer-1,reviewer-2"
```

List candidates:

```sh
python -m agents.english.review_cli --reviewer-id reviewer-1 list
```

Approve only after preparing a complete reviewed JSON entry:

```sh
python -m agents.english.review_cli --reviewer-id reviewer-1 approve 12 --entry-file reviewed-entry.json
```

The JSON entry must include `word`, `pronunciation`, `core_image`, `parts`, `related` (a list), and `example`. An optional `note` is supported. The word must exactly match the pending candidate. Do not label guessed etymology as fact; use `parts` to state when etymology is unverified.

Reject with a reason:

```sh
python -m agents.english.review_cli --reviewer-id reviewer-1 reject 12 --reason "outside the current curriculum"
```

The allowlist is an operator-controlled trust boundary, not a substitute for securing the host environment. Do not expose this CLI through an unauthenticated web route. Approved entries are stored in the existing local SQLite learning database and become available to core-image explanations, quizzes, and daily rotation.

## Verification

Run focused tests with:

```sh
pytest -q tests/test_english_vocabulary_workflow.py
```

No deployment, merge, or automatic approval is performed by this module.
