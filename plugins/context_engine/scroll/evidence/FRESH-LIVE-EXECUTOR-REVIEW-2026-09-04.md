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

## Flex cost-accounting review

Candidate: `318686943fe10f34f00db6d978cf7dab5748b658`.

Independent reviewer `/root/final_fresh_review` returned **NO-GO**: agent,
auxiliary-compression, and judge cost accounting omitted billable cache-read
tokens, so the frozen dollar ceilings were unreliable. The replacement
candidate `c913874fd2162f4cbf37d648115d1708159ab063` freezes Flex cache-read
pricing and a cache-read budget, then aggregates the normalized buckets across
all three paths. It awaits a fresh review; no further live request is
authorized by this record.

## Strict cost-integrity review

Candidate: `c913874fd2162f4cbf37d648115d1708159ab063`.

Independent reviewer `/root/final_fresh_review` returned **NO-GO** again:
auxiliary SessionDB accounting failures were still swallowed, omitted usage
buckets defaulted to zero, and paired/coding runners trusted raw worker costs.
The replacement candidate `017e4dbcf8f36b16af5b00a1cb681cf81261a858`
propagates an evaluator-only accounting failure sink through nested agent
contexts, rejects omitted usage, and derives each accepted cost from the frozen
rates. It awaits a fresh review; no further live request is authorized by this
record.

## Judge-usage boundary review

Candidate: `017e4dbcf8f36b16af5b00a1cb681cf81261a858`.

Independent reviewer `/root/final_fresh_review` returned **NO-GO**: the outer
memory-judge boundary still defaulted omitted subprocess usage buckets to zero,
so a malformed result could evade the shared cap. The replacement candidate
`10869fc0bb736bff89ce365d0d79f13831fd4d21` requires all three integer usage
buckets and rejects reports with no prompt tokens (including cache reads) or no
completion tokens. Its targeted rejection cases pass locally. A fresh complete
candidate-and-manifest review remains required; no further live request is
authorized by this record.

## Final Flex-tier review

Candidate: `10869fc0bb736bff89ce365d0d79f13831fd4d21`.

Independent reviewer `/root/final_fresh_review` returned **GO**. It rechecked
strict complete judge usage (including malformed and zero reports), nested
evaluator-only auxiliary failure-sink propagation, reconstructed costs and
cache budgets, Flex Chat Completions plumbing, provenance, and symmetric arms.
The fresh focused reviewer suite passed 35 tests. No live request occurred
during review. No actionable P0/P1/P2 remains for the frozen manifests.

## ChatGPT OAuth and bounded-parallelism amendment

Candidate: `5e03379f916ad563f359d8782b6577c773ac709d`.

The task owner superseded the OpenRouter Flex route with ChatGPT Codex OAuth
and authorized up to four isolated workers. The amendment removes the
cross-model dollar estimate after the unaccepted partial OpenRouter run exposed
that its auxiliary fallback was priced as Luna. It routes primary, auxiliary,
and judge calls through `openai-codex`/`codex_responses`, binds each isolated
worker to the OAuth store by symlink, and reconstructs report rows in frozen
order after concurrent completion. This is a material route and execution-model
change. **PENDING fresh independent review; it has no GO and authorizes no live
request.** The frozen candidate and manifests are recorded in
[CHATGPT-OAUTH-PARALLEL-REVIEW-2026-09-04.md](CHATGPT-OAUTH-PARALLEL-REVIEW-2026-09-04.md).
