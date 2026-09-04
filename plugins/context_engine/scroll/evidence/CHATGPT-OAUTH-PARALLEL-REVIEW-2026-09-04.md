# ChatGPT OAuth and bounded-parallelism amendment — 2026-09-04

## Status

**PAUSED pending focused review for the expanded attested coding lane.** The controlled memory
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
the caller does not supply an explicit timeout. Its reviewed fresh runtime then
wrote 27 raw results before a returned Responses stream blocked in its first
iterator read. Candidate `757e3cd37160cd942357664139041b3a756eebc8` makes the
owner poll that consumption path at the same no-progress deadline. Its review
found that the consumption daemon lost normal liveness hooks. Candidate
`4de8745a081620b09cc854fa932a817465511a01` transfers both hooks into that
daemon. Its review found that protected cancellation then closed an orphaned
stream too early. Candidate `2556eb457db6a682dc1e8ceb25f06bf409532e78`
retains timer-scoped orphan cleanup. Its reviewed r3 coding runtime wrote 18
raw worker results but no report: two stock compressions emitted substantive
progress yet reached the host's 600-second total ceiling. Candidate
`a46e6727ff630dd4a0e3cb5326aeeee99cb5260e` freezes a 900-second coding-only
host ceiling for both arms and binds schema v2 to coding before provenance or
OAuth. The first schema-v3 resume candidate did not bind its reused artifacts
to the declared r4 source and received P1/NO-GO. Candidate
`a3aa933901da6b57f5763c448235e518e0561985` pins a checked-in attestation of
each reusable r4 result and workspace and awaits focused review.

This amendment supersedes the prior OpenRouter Flex candidate after the task
owner selected the ChatGPT subscription. Its unaccepted partial OpenRouter
runtime is archived below the ignored runtime root. The accounting code priced
an auxiliary non-Luna fallback using Luna Flex rates, so its reported dollar
total could not be reconciled with the provider dashboard and is excluded.

## Frozen candidate

| Item | Value |
| --- | --- |
| Memory implementation commit | `8c32e5e22252c54a39cd1df415d0cbe04bb67774` |
| Coding implementation commit | `f30891b079308efd1c069ce42a034c48dfa92ca0` |
| Provider / auth / billing | `openai-codex` / `chatgpt-codex-oauth` / `chatgpt_subscription` |
| Agent and memory judge model | `gpt-5.6-luna` |
| Maximum isolated workers | `4` |
| Memory manifest SHA-256 | `d7447d09200754d19156511dddab9d58e155f5dffb4c97c9d82d597236b42600` |
| Memory report SHA-256 | `5463a530fa1b7cdaf1d971d839cfcf588dfe513e1925bc6d9a5875caec949dd1` |
| Coding report manifest digest (canonical JSON SHA-256) | `a55be7bf07b5fa3716a0f1483830b24c58940142c5c16caac4f7d34d67b2146e` |

The frozen `seed` remains solely for deterministic task ordering and bootstrap
statistics. It is not sent to the Codex Responses transport.

The coding report's manifest digest is SHA-256 over
`json.dumps(manifest, sort_keys=True, separators=(',', ':'))`, matching
`evals.scroll.coding_live`; it is not the byte hash of the pretty-printed file.

The coding manifest is schema v4 and freezes a 3,000-second host ceiling,
800-second auxiliary timeout (a 3,200-second adapter hard ceiling),
3,300-second worker timeout, and 3,500-second OAuth lease minimum. This
preserves the same model, task set, input budgets, compression behavior, and
four-worker cap for stock and Scroll. Its two raw attestations bind 28 eligible
r4 rows and 54 eligible r5 rows to their exact source manifests, implementations,
runtime names, and lower timeout envelopes. The r5 attempt produced no report:
an actively streaming compression reached its total ceiling and then outlived
the worker guard. Its complete results are nevertheless independently pinned;
the single incomplete r5 row remains fresh work.
Schema v1 is reserved for the completed memory lane; each evaluator rejects
the other lane's schema before provenance, credential, or provider work.

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

The `live-coding-gated-20260904-r2` runtime is also excluded. It wrote 27 raw
results but no durable report: the adapter had bounded `responses.create()`,
but consumed the returned stream on the owner thread, so a blocking first read
again reached the 600-second host compression ceiling. Candidate
`757e3cd37160cd942357664139041b3a756eebc8` moves that consumption to an
attempt-owned daemon and polls the original no-progress deadline. Its direct
regression covers a returned stream whose first `next()` blocks. Focused review
found that its daemon lost thread-local liveness and timing hooks; candidate
`4de8745a081620b09cc854fa932a817465511a01` captures and installs both hooks
inside the consumer. Its review found that protected cancellation then closed an
orphaned stream too early; candidate
`2556eb457db6a682dc1e8ceb25f06bf409532e78` leaves it to attempt-timer cleanup.
Neither the 46-result nor 27-result runtime will be reused.

The `live-coding-gated-20260904-r3` runtime is also excluded. It wrote 18 raw
worker results but no durable report. The adapter received substantive stream
events, so this was not the blocked `responses.create()` or first-iterator-read
failure addressed by the prior candidates. It was a healthy-but-slow long
summary that reached the shared 600-second host ceiling. No r3 raw result will
be reused; the schema-v2 manifest makes the 900-second ceiling explicit and
requires a new focused gate before another attempt.

The first focused review of the 900-second candidate returned P1/NO-GO because
schema v2 was accepted by the memory executor without carrying its ceiling,
while schema v1 reached the coding executor before its missing ceiling field
failed. Candidate `a46e6727ff630dd4a0e3cb5326aeeee99cb5260e` resolves this by
reserving v1 for memory and v2 for coding before provenance, credential, or
provider work; direct regression coverage asserts both rejections.

The `live-coding-gated-20260904-r4` runtime was stopped under the task owner's
direction after 28 complete worker results and several substantively streaming
summaries exceeded its 900-second host ceiling. It produced no report and is
not a completed evaluation. The owner explicitly authorized reuse of only its
complete rows to avoid re-spending the same run budget. Schema v3 names that
runtime and prior canonical manifest digest, permits only the declared timeout
envelope increase, and pins a checked-in result SHA-256 plus recursive workspace
SHA-256 for every reusable job. The manifest pins the attestation's byte hash;
execution verifies both artifact hashes, the deterministic job name, final result
shape, bounded usage, scenario metric, and resulting workspace before recording
every reused row in the final report. Incomplete r4 jobs remain excluded.

The focused reviewer rejected the prior schema-v3 implementation as P1/NO-GO
because the bare result path could be accepted without provenance binding. The
attested replacement accepts no unlisted job: a listed job fails closed on any
result or workspace change, while every unlisted/incomplete r4 job runs fresh.
The reviewer then found that the objective verifier could write Python or
pytest cache files after the workspace hash check. Candidate
`a3aa933901da6b57f5763c448235e518e0561985` disables both writes and regresses
that the full workspace tree remains unchanged during verification.

## Attested resume gate

Independent reviewer: `/root/final_fresh_review`.

On 2026-09-04, the reviewer checked implementation commit
`a3aa933901da6b57f5763c448235e518e0561985` and evidence commit
`67160af88df7ab4281eef8c31b53c087053a694a`. It verified the source-envelope
binding, all 28 result/workspace hashes, fresh execution for unlisted r4 jobs,
non-mutating objective verification, schema/timeout ordering, report audit
fields, and manifest provenance. The reviewer reran its focused checks
(45 passed), Ruff, and `git diff --check`. Disposition: **GO — no actionable
P0/P1/P2.** Commit `20e838f7246f1bdade05d82e4e0f6de2df00dc50` is documentation
only: it records the required r4 resume argument in the operator command.

## Ceiling-schema gate

Independent reviewer: `/root/final_fresh_review`.

On 2026-09-04, the reviewer checked implementation commit
`a46e6727ff630dd4a0e3cb5326aeeee99cb5260e` and evidence commit
`a84be5882c9b3413594e7e1ff0a2311970ca3bed`. The reviewer verified that memory
accepts only schema v1 and coding accepts only schema v2 before provenance or
OAuth, recomputed the coding report's canonical manifest digest
`d824f2f401946c5fe6d740474931fc6321400417429449bb650c90ca0f823337`, and
confirmed the 900-second ceiling is shared by both coding arms and remains
below the 1,200-second adapter/process ceilings and 21-minute OAuth lease
headroom. Coding has no resume path, so r3 raw rows cannot be reused. The
reviewer's relevant suite passed 39 tests. Disposition: **GO — no actionable
P0/P1/P2.**

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
  — 58 passed after the non-mutating-verifier correction.
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

## Refreshed coding gate

Independent reviewer: `/root/final_fresh_review`.

On 2026-09-04, the reviewer checked implementation commit
`509393a38fe43db0f14f31e9560904a54197c039` and evidence/manifest commit
`0a89203ef30a202a14fe213ac6cfa5073983d7cc`. The reviewer recomputed the coding
manifest digest `feb2d251571fd87439bf628d606f48342bfd5a842e686508abbed666ca043c74`,
validated its schema and provenance, and checked the implicit-watchdog timeout,
late-stream cleanup, normal stream behavior, and unchanged four-worker
OAuth/Bubblewrap boundary. The reviewer reran the relevant suites (225 passed);
the owner reran the full focused suite (239 passed), Ruff, and `git diff --check`.
Disposition: **GO — no actionable P0/P1/P2.** This authorizes only a new coding
runtime on `509393a38fe43db0f14f31e9560904a54197c039`; the 46-result
blocked-stream runtime remains excluded. The later r2 stream-consumption
failure supersedes this authorization and requires a focused review of
`757e3cd37160cd942357664139041b3a756eebc8`. That review returned P1/NO-GO
because the daemon dropped normal liveness hooks. Candidate
`4de8745a081620b09cc854fa932a817465511a01` restores them and awaits a fresh
focused disposition. That review returned P1/NO-GO because protected
cancellation closed an orphaned stream before its timer-scoped cleanup; candidate
`2556eb457db6a682dc1e8ceb25f06bf409532e78` restores that contract.

## Final consumption gate

Independent reviewer: `/root/final_fresh_review`.

On 2026-09-04, the reviewer checked implementation commit
`2556eb457db6a682dc1e8ceb25f06bf409532e78` and evidence/manifest commit
`fb4deabbef40f796708945c34e8412e9a68adffa`. The reviewer recomputed the coding
manifest digest `67228f5a0c6aacc6eb65c909880f1b3803e0121976a02f2b2b6c8999775fe82e`,
validated its schema and provenance, and verified the blocked-iterator deadline,
normal liveness/timing hook propagation, protected cancellation cleanup, and
unchanged four-worker OAuth/Bubblewrap boundary. The focused cancellation,
stall, and hook command passed 20 tests; the owner focused suite passed 305
tests, with Ruff and `git diff --check` clean. Disposition: **GO — no actionable
P0/P1/P2.** This authorizes only a new coding runtime; the 46-result and
27-result failed runtimes remain excluded.
