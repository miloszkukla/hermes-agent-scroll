# Fresh live-executor review — 2026-09-04

## Scope

Independent reviewer: `/root/final_fresh_review`.

Candidate: `f86f3bb2f3f3a6de517b82382eb17e30277eb763`.

Inputs: the complete candidate diff and the credential-free
`live-memory-manifest.json` and `live-coding-manifest.json` files.

## Findings and disposition

The initial review identified five P1 findings and one P2 in the live drivers:
coding-tool availability, manifest/source provenance, repeated statistical and
latency evidence, undersized/prose-only coding histories, and judge/corpus
source binding. A later replay-shape finding required the durable coding
history to use OpenAI `function` tool-call envelopes. The final P2 required the
judge import preflight to use the same source checkout working directory as the
judge and to reject untracked shadow packages.

All findings were resolved before this candidate:

- Coding arms use the `coding` toolset, with `context_engine` added only for
  Scroll.
- Live manifests are bound to the committed implementation, PLAN, and
  credential-free manifest; dirty/untracked implementation changes fail closed.
- Coding histories are at least 100K rough tokens and contain valid durable
  terminal failure/retry call-result groups.
- The coding lane performs five paired repeats, emits raw paired outcomes,
  calculates 10,000 paired bootstrap resamples, and reports operation-scoped
  manual-selection and cache-rebuild p95 values.
- LongMemEval and BEAM tracked source trees must be clean; the corpus file is
  SHA-256 pinned. The Scroll source must have no tracked or untracked changes,
  and its Python imports `scroll_eval` from the pinned `evaluation/` tree while
  running with the same source CWD as the judge.

Final disposition: **GO. No actionable P0/P1/P2 remains.**

## Rechecked evidence

- Focused reviewer suite: 17 passed.
- Main focused Scroll/Hermes matrix: 82 passed across 14 files.
- Isolated Stage 0 Monty harness: 18 passed.
- `ruff`, Python compilation, both live-driver `--help` smoke checks, manifest
  validation/provenance, corpus/source checks, and `git diff --check` passed.
- No authenticated model or judge request occurred during review.

## Transport amendment

Candidate: `c17b49e79c31632802433800eb46d4b17463449c`.

An initial authorized stock worker demonstrated that automatic OpenRouter mode
selection chose Codex Responses, which rejects the frozen `seed` request field.
The incomplete attempt has no paired result and is excluded. The replacement
candidate pins `api_mode="chat_completions"` for both arms and preserves the
frozen seed in `request_overrides`; a focused test captures provider, transport,
and seed values without constructing a provider client.

Independent reviewer `/root/final_fresh_review` rechecked the amendment:
**GO preserved; no actionable P0/P1/P2.** Its focused suite passed 18 tests,
and the expanded main focused matrix passed 83 tests across 14 files.

## Coding-worker isolation amendment

Candidate: `6fc652d37c78d0c598cb11b11de12bfe2359ea3b`.

The first corrected coding worker completed but the driver excluded it because
the aggregate output exceeded the then-fixed 32,768-token limit. It also showed
that the worker had not registered the coding workspace under its task ID. The
replacement candidate keeps each auxiliary compression call at 4,096 tokens,
raises the aggregate coding-output allowance to 65,536 tokens, registers the
per-task terminal CWD before the conversation, and clears that override in a
`finally` block. The incomplete worker trace remains excluded and no accepted
paired result exists yet.

Independent reviewer `/root/final_fresh_review` rechecked this amendment:
**GO preserved; no actionable P0/P1/P2.** Its focused suite passed 19 tests,
and the expanded main focused matrix passed 84 tests across 14 files.
