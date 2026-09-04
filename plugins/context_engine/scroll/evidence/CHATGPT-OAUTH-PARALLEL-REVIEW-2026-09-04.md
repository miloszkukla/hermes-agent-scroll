# ChatGPT OAuth and bounded-parallelism amendment — 2026-09-04

## Status

**NO-GO pending a refreshed coding gate.** The controlled memory
lane resumed from its known 79-result checkpoint after a transient retry lost
only an auxiliary billing-route label. The task owner directed that missing
accounting metadata must not invalidate an otherwise valid run. It completed
all 96 stock/Scroll arms on candidate
`8c32e5e22252c54a39cd1df415d0cbe04bb67774`; its durable report is recorded
below and is evidence, not an acceptance claim. The task owner then requested
the reviewer's resume-provenance finding be fixed for future runs. Candidate
`cbc0d324af9966aef1b612d64dd01eac7c56d5ee` binds new saved results to the
frozen manifest/candidate, arm, task, model, history, and probe before reuse.
Legacy bare checkpoints rerun under that future policy. Its refreshed coding
manifest cleared focused review before a fresh coding lane began. The prior
review approved implementation commit `9a53ca9a21ba65f6b5c86089ccedf04a994f7315` and evidence pin
`27666ea2ea3c2298e11a98e9e42cb81cb7118bb6`. The pool lease fails closed
unless its JWT has a finite numeric expiry strictly beyond 21 minutes; direct
provenance, focused tests, Ruff, and diff checks passed. The earlier review
approved implementation commit
`490e6417886933550f3bb45e00cf29b5fcbffb31` after verifying parent-only OAuth
leasing, matched-route auxiliary inheritance, the four-worker cap/order,
protected lease files, Bubblewrap containment and DNS. Preflight then
established that this account's valid OAuth credentials reside in Hermes's
supported `credential_pool` layout, not the singleton store. The prior OAuth
candidate was stopped and excluded when a coding worker issued an absolute
`cd` into the checkout. Its partial results are not accepted; its one checkout
mutation was restored. A fresh coding runtime then completed 46 unaccepted
worker results before two stock automatic-compaction jobs stalled while creating
their Codex Responses streams. Candidate
`509393a38fe43db0f14f31e9560904a54197c039` makes that creation deadline-aware,
closes a late-created stream, and enforces the no-progress deadline even when
the caller does not supply an explicit timeout. The previous GO is invalidated
until this candidate and its revised manifest clear focused review.

This amendment supersedes the prior OpenRouter Flex candidate after the task
owner selected the ChatGPT subscription. Its unaccepted partial OpenRouter
runtime is archived below the ignored runtime root. The accounting code priced
an auxiliary non-Luna fallback using Luna Flex rates, so its reported dollar
total could not be reconciled with the provider dashboard and is excluded.

## Frozen candidate

| Item | Value |
| --- | --- |
| Memory implementation commit | `8c32e5e22252c54a39cd1df415d0cbe04bb67774` |
| Coding implementation commit | `509393a38fe43db0f14f31e9560904a54197c039` |
| Provider / auth / billing | `openai-codex` / `chatgpt-codex-oauth` / `chatgpt_subscription` |
| Agent and memory judge model | `gpt-5.6-luna` |
| Maximum isolated workers | `4` |
| Memory manifest SHA-256 | `d7447d09200754d19156511dddab9d58e155f5dffb4c97c9d82d597236b42600` |
| Memory report SHA-256 | `5463a530fa1b7cdaf1d971d839cfcf588dfe513e1925bc6d9a5875caec949dd1` |
| Coding manifest SHA-256 | `feb2d251571fd87439bf628d606f48342bfd5a842e686508abbed666ca043c74` |

The frozen `seed` remains solely for deterministic task ordering and bootstrap
statistics. It is not sent to the Codex Responses transport.

## Route and isolation contract

- The primary agent uses `openai-codex` with `codex_responses`, the exact
  declared model, and `fallback_model=[]`; a worker rejects a resolved route
  that differs.
- The parent alone resolves and refreshes the caller's OAuth credentials under
  the Hermes auth lock. Before launching a bounded worker or judge, it leases
  a ChatGPT Codex access token with 21 minutes of refresh headroom. The
  supported singleton store and credential-pool layouts are both parent-only;
  a pool lease must have a finite numeric JWT expiry beyond that headroom.
  Workers and judges receive no `auth.json` or refresh token. Runtime/job
  directories are owner-only and the one-use lease file is owner-read/write
  only; a worker unlinks it before constructing the agent.
- Auxiliary compression is explicitly configured for the same Codex route and
  model. When that configured route matches the main route, auxiliary routing
  inherits the already leased access token rather than resolving a credential
  store. Session accounting rejects an auxiliary call using another provider or
  model.
- The model/provider rationale is the separate
  [`MODEL-ACCESS-PREFLIGHT.md`](MODEL-ACCESS-PREFLIGHT.md), which applies the
  `EVALUATION-ERRATA.md` advisory: the upstream harness does not require a
  Qwen-specific lane, while every live arm must retain its declared model and
  provider.
- Coding workers expose only terminal, process, and local file-editing tools;
  they cannot call vision, browser vision, or delegation. Their isolated config
  disables smart approval, avoiding its auxiliary-model route.
- Coding workers run inside Bubblewrap with explicit read-only system and
  source mounts, an empty `/home`, a sanitized environment, a private `/tmp`,
  a read-only resolver file, and a writable bind mount only for that worker's
  job tree at `/work`. Their task workspace is the initial working directory.
  An absolute `cd` can no longer mutate the checkout, another worker's files,
  or inspect the caller's Hermes home.
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

## Unaccepted coding attempt and replacement

The fresh `live-coding-gated-20260904` runtime is excluded. It wrote 46 raw
worker results but no durable report. Two stock automatic-compaction jobs
started normal 42K-token auxiliary summary requests and then produced no stream
for the host's 600-second ceiling; other identical stock jobs completed in
36–44 seconds. The replacement bounds a blocked `responses.create()` call at
the adapter's existing no-progress deadline, lets the normal retry path run,
and closes any stream that arrives after the timeout. No raw result from the
excluded runtime will be reused.

The focused reviewer found that the first replacement only set the no-timeout
watchdog's flag; the owner loop still waited on a blocked stream creation. The
revised candidate treats that flag as a timeout in the owner and adds a direct
no-timeout regression test. This is a reviewer finding, not an accepted result.

## Completed memory lane

The resumed controlled run produced all 96 expected arms (48 stock and 48
Scroll), with valid usage buckets for every agent and judge result. Aggregate
score was 30.5804/48 for stock and 21.4991/48 for Scroll. This is below stock
and does not meet the plan's memory-performance acceptance threshold. It is
retained without normalization or exclusion. A 7-result partial coding attempt
was stopped before this focused gate and is excluded; its ignored runtime files
are not evidence.

## Verification and independent disposition

- `pytest -q tests/evals/test_scroll_hermes_live.py tests/evals/test_scroll_coding_trajectories.py tests/evals/test_scroll_paired_runner.py tests/evals/test_scroll_live_manifest.py tests/plugins/test_scroll_documentation.py tests/agent/test_auxiliary_client.py::TestBuildCodexClient tests/agent/test_codex_cloudflare_headers.py`
  — 237 passed after the resume-provenance correction.
- `ruff check agent/auxiliary_client.py evals/scroll/hermes_live.py
  evals/scroll/coding_live.py tests/evals/test_scroll_hermes_live.py
  tests/agent/test_auxiliary_client.py tests/agent/test_codex_cloudflare_headers.py`
  — passed.
- Both live manifests validate through `validate_live_manifest()` and contain
  no credential field.
- Authentication smoke (no model request): `get_codex_auth_status()` under
  `HERMES_HOME=/home/codex/.hermes` reported `logged in`.

The prior independent review cleared implementation commit
`5e03379f916ad563f359d8782b6577c773ac709d`, but it predates the Bubblewrap
containment and resume-provenance changes and is not the approval for the
refreshed coding candidate.

## Focused coding gate

Independent reviewer: `/root/final_fresh_review`.

On 2026-09-04, the reviewer checked implementation commit
`cbc0d324af9966aef1b612d64dd01eac7c56d5ee` and evidence/manifest commit
`23995f404ab6dbe93dddba423cb9cb25b5d5c82f`. The reviewer verified
provenance-bound future resume, coding-worker compatibility, coding-manifest
provenance, OAuth/Bubblewrap containment, and the four-worker cap. The focused
suite passed 237 tests; Ruff and `git diff --check` passed. Disposition:
**GO — no actionable P0/P1/P2.** This previous disposition authorized the
first fresh coding runtime only. It is superseded by the blocked-stream fix;
the completed 8c memory report remains evidence and does not meet acceptance.
