# ChatGPT OAuth and bounded-parallelism amendment — 2026-09-04

## Status

**GO for the frozen ChatGPT Codex OAuth candidate.** No live result is accepted
yet; this gate authorizes only a fresh run against the frozen manifests.

This amendment supersedes the prior OpenRouter Flex candidate after the task
owner selected the ChatGPT subscription. Its unaccepted partial OpenRouter
runtime is archived below the ignored runtime root. The accounting code priced
an auxiliary non-Luna fallback using Luna Flex rates, so its reported dollar
total could not be reconciled with the provider dashboard and is excluded.

## Frozen candidate

| Item | Value |
| --- | --- |
| Implementation commit | `5e03379f916ad563f359d8782b6577c773ac709d` |
| Provider / auth / billing | `openai-codex` / `chatgpt-codex-oauth` / `chatgpt_subscription` |
| Agent and memory judge model | `gpt-5.6-luna` |
| Maximum isolated workers | `4` |
| Memory manifest SHA-256 | `86a31fcdb1f234cfbbf98da07c959a7f2fff1cbb89631098eecb3193f9407bdf` |
| Coding manifest SHA-256 | `11c5f0c4c662d20067a6eb00c70299278a9b75ec0da70ea70f1f88401414ff94` |

The frozen `seed` remains solely for deterministic task ordering and bootstrap
statistics. It is not sent to the Codex Responses transport.

## Route and isolation contract

- The primary agent uses `openai-codex` with `codex_responses`, the exact
  declared model, and `fallback_model=[]`; a worker rejects a resolved route
  that differs.
- Each worker has an isolated `HERMES_HOME` and a symlink to the caller's
  `auth.json`, not a copied credential. It must resolve a logged-in ChatGPT
  Codex OAuth credential before starting.
- Auxiliary compression is explicitly configured for the same Codex route and
  model. Session accounting rejects an auxiliary call using another provider or
  model.
- Coding workers expose only terminal, process, and local file-editing tools;
  they cannot call vision, browser vision, or delegation. Their isolated config
  disables smart approval, avoiding its auxiliary-model route.
- The pinned-source memory judge receives the caller's `HERMES_HOME` and the
  Hermes source path explicitly. It resolves its client through the same Codex
  OAuth route rather than an OpenRouter or direct API-key client.

## Bounded parallelism contract

The memory lane submits 96 stock/Scroll arm jobs and the coding lane submits
200 five-repeat arm jobs through executors capped by the manifest's four
workers. On a job failure, queued futures are cancelled and the lane fails.
Completed results are reconstructed by their frozen job index, so reports keep
the canonical task, repeat, and arm ordering regardless of completion order.

Token budgets remain fail-closed for every primary, auxiliary, and judge result.
The durable reports intentionally contain no synthesized dollar total because a
ChatGPT subscription is allowance-based and the previous cross-model dollar
estimator was invalid.

## Verification and independent disposition

- `pytest -q tests/evals/test_scroll_*.py tests/plugins/test_scroll_documentation.py`
  — 35 passed.
- `ruff check evals/scroll tests/evals/test_scroll_paired_runner.py
  tests/evals/test_scroll_live_manifest.py tests/evals/test_scroll_hermes_live.py`
  — passed.
- Both live manifests validate through `validate_live_manifest()` and contain
  no credential field.

Independent reviewer `/root/final_fresh_review` rechecked implementation commit
`5e03379f916ad563f359d8782b6577c773ac709d` and evidence commit
`b92a40ca11964231c73076df09d372a652093871`. It found no actionable
P0/P1/P2: the primary, compression-auxiliary, and judge routes are Codex OAuth
Responses with no fallback; the worker symlink and judge environment are scoped;
the restricted coding toolset preserves the four-worker bound; both manifests
validate and verify provenance; and no synthesized dollar fields remain. Its
focused suite passed 28 tests, with Ruff and diff checks clean. The reviewer did
not make an authenticated request.
