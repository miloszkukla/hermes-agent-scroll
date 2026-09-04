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
| Implementation commit | `ff21affcfc09f0371392186a02b941537eb50713` |
| Provider / auth / billing | `openai-codex` / `chatgpt-codex-oauth` / `chatgpt_subscription` |
| Agent and memory judge model | `gpt-5.6-luna` |
| Maximum isolated workers | `4` |
| Memory manifest SHA-256 | `337e1827ebbc0bf14116cd8109e5e022825c361fe0678959f2562419e650224f` |
| Coding manifest SHA-256 | `d0ead17e87d577dab089a0e9a01ce68d7085df19fbbd3e74142d134753b891c5` |

The frozen `seed` remains solely for deterministic task ordering and bootstrap
statistics. It is not sent to the Codex Responses transport.

## Route and isolation contract

- The primary agent uses `openai-codex` with `codex_responses`, the exact
  declared model, and `fallback_model=[]`; a worker rejects a resolved route
  that differs.
- The parent alone resolves and refreshes the caller's OAuth store under the
  Hermes auth lock. Before launching a bounded worker or judge, it leases a
  ChatGPT Codex access token with 21 minutes of refresh headroom. Workers and
  judges receive no `auth.json` or refresh token; a worker unlinks its one-use
  lease file before constructing the agent.
- Auxiliary compression is explicitly configured for the same Codex route and
  model and uses the already leased access token rather than resolving a
  credential store. Session accounting rejects an auxiliary call using another
  provider or model.
- Coding workers expose only terminal, process, and local file-editing tools;
  they cannot call vision, browser vision, or delegation. Their isolated config
  disables smart approval, avoiding its auxiliary-model route.
- Coding workers run inside Bubblewrap with explicit read-only system and
  source mounts, an empty `/home`, a sanitized environment, a private `/tmp`,
  and a writable bind mount only for that worker's job tree at `/work`. Their
  task workspace is the initial working directory. An absolute `cd` can no
  longer mutate the checkout, another worker's files, or inspect the caller's
  Hermes home.
- The pinned-source memory judge uses an empty temporary `HERMES_HOME` and its
  leased Codex access token. It has no caller auth store or inherited provider
  environment.

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

- `pytest -q tests/evals/test_scroll_hermes_live.py tests/evals/test_scroll_coding_trajectories.py tests/evals/test_scroll_paired_runner.py tests/evals/test_scroll_live_manifest.py tests/plugins/test_scroll_documentation.py tests/agent/test_auxiliary_client.py::TestBuildCodexClient tests/agent/test_codex_cloudflare_headers.py`
  — 45 passed.
- `ruff check agent/auxiliary_client.py evals/scroll/hermes_live.py
  evals/scroll/coding_live.py tests/evals/test_scroll_hermes_live.py
  tests/agent/test_auxiliary_client.py tests/agent/test_codex_cloudflare_headers.py`
  — passed.
- Both live manifests validate through `validate_live_manifest()` and contain
  no credential field.

The prior independent review cleared implementation commit
`5e03379f916ad563f359d8782b6577c773ac709d`, but it predates the Bubblewrap
containment change and is not a GO for this candidate. A new reviewer must
recheck the worker boundary, route, manifests, and four-worker cap before a
fresh live run begins.
