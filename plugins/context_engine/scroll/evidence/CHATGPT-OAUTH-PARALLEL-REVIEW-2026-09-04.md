# ChatGPT OAuth and bounded-parallelism amendment — 2026-09-04

## Status

**PAUSED pending a fresh independent review.** The prior OAuth candidate was
stopped and excluded when a coding worker issued an absolute `cd` into the
checkout. The worker's partial results are not accepted; its one checkout
mutation was restored. The replacement runs coding workers under Bubblewrap,
with the checkout read-only and only that worker's job tree writable.

This amendment supersedes the prior OpenRouter Flex candidate after the task
owner selected the ChatGPT subscription. Its unaccepted partial OpenRouter
runtime is archived below the ignored runtime root. The accounting code priced
an auxiliary non-Luna fallback using Luna Flex rates, so its reported dollar
total could not be reconciled with the provider dashboard and is excluded.

## Frozen candidate

| Item | Value |
| --- | --- |
| Implementation commit | `4735fadb8b94d2190986fe1366b51c07c2d3bd09` |
| Provider / auth / billing | `openai-codex` / `chatgpt-codex-oauth` / `chatgpt_subscription` |
| Agent and memory judge model | `gpt-5.6-luna` |
| Maximum isolated workers | `4` |
| Memory manifest SHA-256 | `31104d67331eb3cf0408d66db5f3a83b0f28cbc5c32ee4bf69de473014923190` |
| Coding manifest SHA-256 | `0cda70e322ad2b236825a11075e80bf08023f64f209efa9e87856a38639a96da` |

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
- Coding workers run inside Bubblewrap with a read-only host filesystem, a
  writable bind mount only for that worker's job tree, a private `/tmp`, and
  their task workspace as the initial working directory. An absolute `cd` can
  no longer mutate the checkout or another worker's files.
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

- `pytest -q tests/evals/test_scroll_hermes_live.py tests/evals/test_scroll_paired_runner.py tests/evals/test_scroll_live_manifest.py tests/plugins/test_scroll_documentation.py`
  — 26 passed.
- `ruff check evals/scroll tests/evals/test_scroll_paired_runner.py
  tests/evals/test_scroll_live_manifest.py tests/evals/test_scroll_hermes_live.py`
  — passed.
- Both live manifests validate through `validate_live_manifest()` and contain
  no credential field.

The prior independent review cleared implementation commit
`5e03379f916ad563f359d8782b6577c773ac709d`, but it predates the Bubblewrap
containment change and is not a GO for this candidate. A new reviewer must
recheck the worker boundary, route, manifests, and four-worker cap before a
fresh live run begins.
