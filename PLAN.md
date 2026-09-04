# Sandboxed Scroll Context-Engine Plugin

## Status

Planning is complete pending the mandatory Stage 0 stop/go gate. Implementation
is paused.

## References and authority

1. Hermes Agent release `v2026.8.31`, commit
   `29112bef099274229cadff79cdff7bf7b99c4b77`, defines the host and plugin
   contracts.
2. Scroll commit `313077708ea105cc79bf0a997338e14dae916f8c` defines the
   vendored implementation behavior.
3. QwenPaw `scroll-research` commit
   `3db60c5975187fc7c549e16573567a7cd21fd51f` is a behavioral and evaluation
   oracle only where this plan explicitly ports a case.
4. [Context as an Environment: Programmatic Context Management for Long-Horizon Agents](https://arxiv.org/abs/2608.21690)
   is the conceptual and evaluation reference, not an implementation contract.

If these sources differ, the pinned Hermes and Scroll commits plus this plan
govern delivery. This integration intentionally changes the sandbox runtime and
excludes the paper's broader `repl_exec`/LOCA environment-tool surface. The
paper's published scores are context, not acceptance baselines.

The Hermes refresh from `2a598aad1c398e95b3325a0f100f5c28efa63d12` to the
stable `v2026.8.31` release leaves the context-engine ABC, plugin loader, and
plugin documentation unchanged. Session persistence and compaction did change;
this plan therefore treats row identity as generation-scoped, contains the
public snapshot read lifecycle inside Hermes, and accounts for transient
persistence/compaction markers and carried-tail cloning.

## Mandatory baseline/worktree preflight

The remote `codex/scroll-plugin` branch is currently checked out at the old
Hermes pin with staged changes to `.gitignore`, `.python-version`, and
`PLAN.md`. Before Stage 0, record the current HEAD, branch, status, staged and
unstaged diffs, and file hashes; preserve that complete state in a named,
recoverable backup commit/branch or equivalent reviewed patch artifact. Verify
the recovery artifact before changing the checkout.

Fetch from the authenticated upstream remote, verify the annotated
`v2026.8.31` tag object and its peeled commit, then materialize commit
`29112bef099274229cadff79cdff7bf7b99c4b77` in a new worktree/branch or advance
the existing branch only after the recovery artifact is proven, then reapply
the intended local plan/bootstrap changes without dropping unrelated work.
Record the resulting diff and require `git rev-parse HEAD` to equal the pinned
commit before Stage 0 or adapter implementation begins. A dirty checkout is
allowed only for the explicitly inventoried, preserved integration changes.

## Goal

Add `niceIrene/Scroll` to a Hermes Agent fork as one `scroll` context-engine
plugin. It exposes exactly one tool, `scroll_repl`: an upstream-compatible
persistent Scroll REPL executed only by the Monty sandbox. It retains long-run
coding-session context, including Scroll's model-authored headlines, eviction
index, and stable sequence navigation, without giving the model a raw CPython
or host-shell surface.

This is not claimed to be identical to the paper's CPython implementation.
Monty is experimental and implements a Python subset; equivalence is a Stage 0
compatibility result, not an assumption.

## Architecture decisions

- `scroll_repl` is the sole plugin tool schema. There is no restricted mode and
  no host `scroll_search`, `scroll_expand`, or `scroll_query` tool schema.
- Scroll source is vendored at
  `plugins/context_engine/scroll/vendor/scroll_context/`, pinned to Apache-2.0
  commit `313077708ea105cc79bf0a997338e14dae916f8c`. `UPSTREAM.md` records
  its license/NOTICE obligation, exact commit, local patch inventory, and
  update procedure. All absolute `scroll_context` imports are patched to
  package-relative imports; package data is retained.
- Hermes remains canonical. It gains a minimal public read-only
  `CanonicalHistorySnapshot` interface because plugin hooks alone cannot
  rebuild recall state after compaction. The plugin never reads `state.db`, a
  SQLite handle, or database path.
- The REPL runs only in `pydantic-monty==0.0.21`, using its local subprocess
  worker—not raw CPython, RestrictedPython, a Monty WebSocket remote, an
  NsJail-only CPython worker, or an unsafe fallback. If Monty is unavailable,
  mismatched, or fails Stage 0, the plugin fails closed and implementation
  stops for an architecture review.
- Inside Monty, `ms` is a bootstrapped read-only proxy and `or_terms` is a
  bootstrapped helper. Both reach only narrowly typed host callbacks; no
  SQLite object/path, arbitrary host object, filesystem mount, optional OS
  callback, credential, or environment variable crosses the boundary.
- `ms` retains the upstream `search`, `expand`, and `sql_query(sql, params)`
  semantics. `sql_query` is available only inside Monty and accepts exactly one
  bounded read-only `SELECT` or CTE over the fixed history schema; it is not a
  host tool, SQLite handle, or general database capability.
- `scroll_repl` restores the upstream Scroll protocol: model-authored
  headlines, eviction-index navigation, stable sequence IDs, persistent typed
  namespace, and `ms` recall operations. It does not simultaneously expose
  overlapping host recall tools.
- Delivery targets the existing disposable Contabo Cloud VPS 6 worker (x86_64,
  6 vCPU, 12 GiB RAM, Ubuntu 26.04). Hermes, Scroll, their evaluation lanes,
  and the Monty client run in one project-local uv-managed CPython 3.12.14
  environment. Ubuntu's system CPython 3.14 remains installed and unmodified.
  The remote's isolation is defense in depth, not the sandbox's security proof.
  Runtime operation is display-independent, but the validation lane includes
  Hermes's existing Electron Playwright suite under Cage/headless Wayland for
  desktop end-to-end and visual regression coverage.

## Approval and Hermes reuse boundaries

At Hermes Agent `v2026.8.31` commit
`29112bef099274229cadff79cdff7bf7b99c4b77`,
`approvals.mode` (`manual`, `smart`, or `off`) authorizes flagged terminal and
`execute_code` operations, while ACP edit policies are separate. They are not
isolation controls. The Monty sandbox is required in every approval mode. V1
`ms`/`or_terms` callbacks are read-only and need no per-call approval; a future
host-effecting callback must dispatch under current Hermes per-cell/session
authority and approval. Approval must never disable the interpreter sandbox.

Reuse the contracts and test patterns from `tools/code_kernel.py` where they
fit: session ownership, serialized calls, authenticated RPC, stdout/stderr caps,
timeout/interrupt/kill, restart/state-lost reporting, idle/LRU cleanup, and
session-bound teardown. Extract narrowly reusable lifecycle/supervision helpers
only if needed. Do not reuse `execute_code` or local CPython as the boundary:
`tools/code_execution_tool.py` documents its environment scrubbing, tool
whitelist, and output redaction as non-jail measures. Local/SSH terminals are
not isolation, and Docker/remote terminal backends can retain network, mounts,
persistence, or synchronized credentials. A replacement terminal backend needs
a separate security review; v1 stays Monty-only and fails closed.

## Runtime and Monty supply-chain lock

The target is Ubuntu 26.04 x86_64 with a project-local CPython 3.12.14. Python
3.12 is the one-environment compatibility intersection: Hermes requires
`>=3.11,<3.14`, pinned Scroll's `evaluation/pyproject.toml` requires
`>=3.12,<3.13`, and Monty 0.0.21 publishes cp312 wheels. It is not a Monty-only
requirement. The repository `.python-version` must contain the exact patch
version `3.12.14`, not the floating minor version `3.12`. The lock admits only:

| Artifact | Version / target | SHA-256 |
| --- | --- | --- |
| `uv` | `0.12.9`, x86_64-unknown-linux-gnu archive | `ec7a99cd05e0cd7f80243f135ce1361c76835cb0ee60055d14d20eba8eba1460` |
| CPython | `3.12.14+20260901`, x86_64-unknown-linux-gnu install-only stripped archive | `72748da13197c1fb161e3afeef20a6a385ff24f2165e6e2758e47008e7faba4c` |
| `pydantic-monty` | `0.0.21` universal wheel | `7e84ef67b9e72f751819f6e7d4761eae3e3aa782d396f7777cd7948a05f4a5f7` |
| `pydantic-monty-client` | `0.0.21`, cp312 manylinux_2_28 x86_64 | `6272ec5f21aaabcbc23d9ebc57dc8c89c3903bcb4c2d9821d742fcc6b8449c1c` |
| `pydantic-monty-runtime` | `0.0.21`, cp312 manylinux_2_28 x86_64 | `31efcfa7e821a0420e2f34866df0767d2924b445e85c875c5f946d7f6adbe44c` |
| worker | `<plugin-venv>/bin/monty` from that runtime wheel | `bc4767743e5fb9fa360fbee21ded25e2642d8ad89a5c4f81b02a67d66c93a385` |
| worker protocol | local subprocess protocol | version `1`, supported range `1..1` |

Monty is MIT-licensed and experimental. Bootstrap verifies the uv and CPython
archive digests before creating the project-local environment; it does not add
managed Python launchers to the global path or replace system Python. Startup
then verifies `sys.executable`, exact Python version, ABI, libc and SQLite
versions, every package and worker digest, fixed worker path, Monty version, and
protocol range before creating a checkout. The delivery includes a dependency
lock, SBOM, licenses, verification log, and update procedure. Any mismatch
fails closed. The worker receives no filesystem mounts or optional OS callbacks
in v1.

At plan refresh time the host has no `uv` executable on its searched paths. Its
existing project `.venv` reports CPython 3.12.14 and Monty 0.0.21 with the
expected worker hash, but that observation is not the supply-chain receipt.
Stage 0 must first install the locked uv 0.12.9 artifact, record its digest and
`uv --version`, and either prove the existing interpreter archive provenance or
create a fresh locked environment while keeping the prior environment
recoverable until validation succeeds.

## Mandatory Stage 0: Monty stop/go spike

Before adapter work, create a small pinned test harness and prove all of the
following on the exact lock above:

1. Every Python construct used by Scroll's protocol and planned evaluations
   executes with equivalent observable behavior; variables and definitions
   persist across `feed_run` calls.
2. Reserved `ms` and `or_terms` can be synchronously rebound after model
   shadowing, only accept bounded JSON-safe values, and correctly reject deeply
   nested/unsupported values. Expression return values are discarded; only
   bounded `print`/stdout output becomes the tool result.
3. The adapter can generate a bounded working-memory digest without serializing
   the Monty checkout, and all model-visible `ms` calls route through typed
   search, expand, and bounded read-only SQL-query callbacks.
4. Tight loops, memory exhaustion, recursion exhaustion, and stdout overflow
   meet configured controls. A timeout/crash kills only the worker, the pool
   replaces it, and Hermes remains responsive.
5. The worker has an empty ambient environment and no filesystem, network,
   process, or path through permitted imports, introspection, or serialization
   to an ambient host capability. Escape attempts are acceptance tests, not
   merely assumptions.

If any required Scroll semantic cannot be reproduced or any containment test
fails, stop. Do not add a CPython, WebSocket, embedded interpreter, or other
unsafe fallback; reopen architecture review.

## Canonical history contract

Hermes returns an immutable, transactionally consistent
`CanonicalHistorySnapshot` rather than a database handle. A public `SessionDB`
snapshot method internally acquires one read connection, establishes one
consistent read transaction, fully materializes immutable DTOs, and releases
the transaction and connection before returning. The plugin never receives or
retains `_read_ctx`, a connection, context manager, database path, or other
storage capability.

The snapshot includes logical lineage, generation, high-water mark,
generation-scoped stable `_row_id` and order keys, and only committed,
non-undone rows. Active and compacted recall-eligible rows include role,
redacted text/content references, normalized tool metadata, correlation
metadata, and sensitivity/fidelity classification. `_db_persisted` and
`_compaction_tail` remain private transient Hermes markers and are not projected;
persisted `_compressed_summary` is normalized to a public
`is_compressed_summary` field. Reset, deleted, and undone content is neither
returned nor indexed.

At each selection the adapter merges the snapshot with the hook's uncommitted
suffix. It deduplicates by `_row_id` and drops suffix entries committed at or
below the snapshot high-water mark. Hermes owns lineage traversal, generation,
and order; the plugin receives data only.

Committed compaction can archive carried-tail originals and insert active
clones with new row IDs, including concurrent rows above the compaction
watermark. Row IDs and navigation handles are therefore never treated as stable
across generations. The post-commit boundary atomically advances the projection
epoch, invalidates old handles/cursors, rebuilds the projection, and rebinds
`ms` before new recall execution is accepted.

## Lifecycle and bounded selection

| Event | Key/state | Required action |
| --- | --- | --- |
| First start | new logical lineage | Verify Monty lock, create locked cache metadata and one checkout, build from snapshot. |
| Process resume | same lineage/fingerprint | Validate high-water/fingerprint, reconcile or rebuild cache; report namespace reset because no checkout is serialized. |
| In-place compaction | same session, new generation | Keep live checkout; after the committed boundary atomically invalidate old handles, rebuild the projection, and rebind `ms`. |
| Rotating compaction | child session, inherited lineage | Rebind physical ID to lineage and retain the checkout in-process; after commit atomically invalidate old handles, rebuild the projection, and rebind `ms`. |
| Reset/new session | lineage changes | Invalidate navigation, kill/discard checkout, close resources, and never replay old rows. |
| End | current session | Kill/discard checkout, release cache lock, and persist no namespace. |
| Worker crash/timeout | active lineage | Kill/reap, replace worker, discard namespace, return explicit namespace-reset result; canonical recall remains available through `ms`. |
| Cache ahead/behind/corrupt | fingerprint/high-water mismatch | Invalidate projection and rebuild atomically from canonical snapshot under lock. |
| Concurrent lineage access | owner exists | Serialize cache/checkout ownership; non-owner returns deterministic bounded fallback and retries on a later request. |

Callbacks are idempotent for lineage, generation, and high-water mark.
`compress()` is pure over Hermes's deep snapshot: it never starts, calls,
inspects, mutates, waits on, or serializes a live Monty checkout. Only a
post-commit compression boundary updates cache state.

The host-pinned request set, in canonical order, is all leading
system/developer policy, the fixed REPL protocol, and current task/user intent
selected by a documented Hermes rule. Tool groups are indivisible. Define
`input_target = context_window - completion_reserve - tool_schema_reserve -
system_reserve - provider_margin`. Only unpinned groups enter that target. If
pinned content itself overflows, retain policy/protocol and truncate only the
oldest non-policy task detail via the deterministic canonical-tail fallback.

Selection catches cache, lock, FTS, corruption, rebuild, and worker failures;
it always returns that bounded pinned-tail fallback instead of failing open to
the original oversized transcript. The fallback is stable for provider retries.

## Sandboxed `scroll_repl` surface

The tool accepts a bounded Python snippet and executes it in the active Monty
checkout. Its upstream-compatible prompt teaches headlines and stable sequence
navigation. `ms` exposes only typed, read-only operations backed by host
callbacks: search, expand, and `sql_query(sql, params)`. `or_terms` is a pure
helper over bounded values. Every navigation handle is bound to logical lineage,
canonical generation, and projection epoch; stale handles fail with a bounded
refresh-required result rather than resolving against replacement rows.

Callbacks are the trust boundary. They validate current logical lineage,
generation, recall eligibility, and input/output schemas; use only a read-only
SQLite connection with fixed schema/columns, authorizer, `query_only`, opcode
and time budget, row/byte caps; and serialize JSON-safe bounded results.
`sql_query` rejects multi-statement input and anything except one `SELECT` or
CTE; writes, DDL, PRAGMA, ATTACH/DETACH, extension loading, virtual-table
creation, and administrative operations are denied. Callbacks never return
handles, paths, or raw host objects. `params` is a bounded typed sequence or
mapping of JSON-safe scalar values, validated before execution and passed only
as prepared-statement bindings; SQL interpolation or concatenation is forbidden.

The worker is supervised with a wall-clock request timeout, in-sandbox duration,
memory, recursion, input, and stdout/output limits. On timeout/crash/invalid
protocol it is killed/reaped and replaced; it cannot hang Hermes. These controls
do not license untested capability: no mounts, OS callbacks, WebSocket worker,
or fallback runtime is enabled.

## Cache, redaction, and fidelity

- Cache paths derive from sanitized hashes of logical lineage, use 0700
  directories and 0600 files, reject no-follow/symlink/path traversal, and use
  an interprocess lock.
- Atomic rebuild is same-filesystem temporary file, flush/fsync, and replace
  while holding the lock. The fingerprint includes schema, Scroll commit,
  Monty lock, and normalization version.
- Cache stores only host-redacted canonical fields. Hidden reasoning and
  secret-bearing fields are excluded. Egress repeats redaction and labels
  recovered history as untrusted. Non-text/artifact payloads return bounded
  references/digests marked `degraded`, never fabricated raw bytes.
- FTS5 absence/corruption, crash recovery, retention/purge, cache-ahead state,
  and same-lineage concurrency follow the lifecycle table above.

## Upstream test and evaluation reuse

All borrowed tests, fixtures, prompts, and dataset adapters carry a provenance
entry with repository, commit, path, license, local changes, and update rule.
The two reviewed sources are Scroll commit
`313077708ea105cc79bf0a997338e14dae916f8c` (Apache-2.0) and the paper's
QwenPaw `scroll-research` commit
`3db60c5975187fc7c549e16573567a7cd21fd51f` (Apache-2.0).

| Evidence source | Reuse rule | Exclusions |
| --- | --- | --- |
| Scroll package `tests/` | Run unmodified after vendoring/import isolation: eviction/index and budget behavior, history/FTS/corruption, stable sequence navigation, runtime namespace/output limits, and the eviction-index simulation. Add Monty-specific assertions rather than weakening CPython expectations. | CPython executor results do not prove Monty containment or semantic compatibility; Stage 0 remains independent. |
| Scroll `evaluation/tests/` | Run the unmodified config, ingest, runner, judge, comparison, and reference-agent unit tests as an upstream-drift guard. Adapt its loaders/judges through a thin Hermes result adapter, keeping gold data outside model context. | Do not make the Scroll reference agent loop the implementation under test. |
| QwenPaw `scroll-research` tests | Port only Hermes-applicable behavioral oracles: idempotent reconcile/resume, complete and parallel tool groups, active-turn/result acknowledgement, one-shot overflow retry, FTS5-to-LIKE degradation, bounded paging and snapshot-bound cursors, corrupt-store/startup recovery, failure-not-empty results, headline hiding/stream splits, index roll-up, SQL-authorizer escapes, and prepared-parameter injection cases. | Do not port QwenPaw host-file sync, continuation-summary, two-tool registration, unsandboxed opt-in/governor, or AgentScope-private-contract behavior. |
| QwenPaw browser E2E | Reuse scenario ideas only. Translate them to deterministic Hermes mock-inference fixtures and blocking DOM assertions. | Do not copy its conditional/log-only checks or live-model timing loops as acceptance tests. |
| Hermes `v2026.8.31` `evals/compaction` | Reuse compatible fixtures, result serialization, scoring, and report schema through a stock/plugin adapter for paired runs. | The existing harness is not Scroll integration proof and does not replace plugin, sandbox, lifecycle, or recall tests. |

The paper's LongMemEval and BEAM protocols are reusable memory evaluations.
LOCA is not a required gate: the reviewed Scroll repository has no compatible
LOCA runner, and the paper's QwenPaw setup relies on `repl_exec` plus
programmatic environment tools that this read-only `ms` plugin does not expose.

## Live-model access and credential boundary

Stage 0, focused/unit/integration tests, deterministic synthetic histories, and
desktop E2E/visual tests use fixtures or mock inference and require no live
model credential. Model-backed LongMemEval/BEAM and coding-trajectory lanes
require separate preflight for the agent-under-test model and any judge model.

The preferred interactive pilot may use Hermes's `openai-codex` provider with
the user's explicitly authorized ChatGPT-subscription login. This is a
Hermes-specific integration, not an OpenAI-supported third-party-client
contract, and it is not the sole permitted evaluation credential. Immediately
before live evaluation, freeze the provider, exact model/judge identities,
account/access class, temperature/seed, token budgets, rate-limit conditions,
and cost/usage ceiling in the evaluation manifest. Stock and plugin arms use
the same frozen settings. Any provider, model, or authentication change is an
explicit reviewed manifest revision and restarts affected paired runs; there is
no silent fallback.

Authenticate interactively only at the live-evaluation boundary. Credentials,
refresh tokens, and account identifiers stay outside the repository, fixtures,
cache, traces, screenshots, and reports and never cross into Monty. Do not copy
Codex's credential store into Hermes. Record only the provider/auth mode,
credential-free smoke-test result, model availability, limits, and manifest
revision. Scheduled automation must use an explicitly approved non-interactive
credential mechanism rather than exporting a personal browser session.

## Documentation deliverables

- `plugins/context_engine/scroll/README.md` documents purpose, enablement and
  configuration, exact runtime prerequisites, the `scroll_repl`/`ms` contract,
  context and output limits, cache lifecycle/rebuild/purge, failure modes,
  troubleshooting, and the distinction between approvals and Monty isolation.
- `UPSTREAM.md` remains the source/license/local-patch/update record. A separate
  plugin security document records the threat model, callback and credential
  boundary, fail-closed behavior, known Monty limitations, and responsible
  procedure for changing the sandbox or adding a host effect.
- An evaluation runbook documents credential-free versus live-model lanes,
  authentication preflight without secret capture, frozen manifests, review
  gates, exact commands, expected artifacts, cost controls, paired-run restart
  rules, and result interpretation.
- Update Hermes's existing English context-engine developer guide and built-in
  plugin/user documentation for the new public snapshot contract and `scroll`
  plugin. Keep implementation detail in the plugin docs and link rather than
  duplicating it broadly.

Documentation examples are tested: configuration snippets must parse, commands
must run on the reference host, internal links must resolve, and generated logs
or screenshots must contain no credentials or hidden history.

## Implementation steps

1. Complete the mandatory baseline/worktree preflight and prove that the
   implementation baseline is the pinned Hermes commit with all prior local
   changes recoverable.
2. Verify and bootstrap the locked uv archive, install or provenance-verify the
   locked project-local CPython 3.12.14 build without changing system Python,
   record the runtime identity, then complete Stage 0 and record a signed
   stop/go report. Stop immediately on a failed required semantic or containment
   check.
3. Add and test the public canonical snapshot interface: high-water, lineage,
   active/compacted/undone/reset semantics, immutable snapshot, and suffix merge.
4. Vendor Scroll at the pinned commit; preserve Apache-2.0 materials, patch
   imports, retain package data, produce `UPSTREAM.md`, and run upstream tests.
5. Add the locked Monty environment, binary/protocol startup verification,
   SBOM/license/update artifacts, and fail-closed worker supervisor using only
   the reusable `code_kernel` lifecycle patterns, never `execute_code`.
6. Add `plugins/context_engine/scroll/__init__.py`, `plugin.yaml`, and the
   adapter; register only `scroll_repl`; bootstrap `ms`/`or_terms`; implement
   the upstream headline/sequence protocol and typed host callbacks.
7. Implement lifecycle, pinned request budgeting/fallback, cache recovery,
   redaction, and pure compression without live checkout access.
8. Define deterministic desktop fixtures and scenario scripts for the visible
   Scroll states, add semantic and visual Electron Playwright coverage, and
   record or review the target-branch screenshot baselines.
9. Add the pinned test-provenance manifest, upstream test runners, QwenPaw
   behavioral ports, the Scroll-evaluation-to-Hermes result adapter, and the
   compatible Hermes `evals/compaction` fixture/result/scoring adapter. Complete
   and verify the plugin, security, evaluation, and Hermes user/developer docs.
10. Run the risk-focused test matrix, desktop typecheck/unit/E2E/visual and
    packaged-app smoke tests, then the relevant Hermes suite. Pass the mandatory
    pre-evaluation readiness gate before any live-model benchmark lane.
11. Push the reviewed pre-evaluation checkpoint, run the authorized live-model
    evaluation lanes, complete the final evidence review, and push the final
    delivery checkpoint under the Git rules below.

## Test matrix

- Stage 0 construct compatibility, persistent variables/definitions, `ms` and
  `or_terms` shadow/rebind, synchronous callbacks, nested value bound, stdout
  only, working-memory digest, tight loop, OOM, recursion, output cap, crash
  replacement, empty environment, denied filesystem/network/process access and
  denied ambient-capability paths through imports/introspection/serialization.
- Locked uv/CPython archive verification; exact `sys.executable`, CPython
  3.12.14, ABI, libc, and SQLite identity; project-local CLI, gateway, desktop,
  Scroll evaluation, and test-launch paths; and proof that system CPython 3.14
  and global Python launchers remain unchanged.
- Baseline preflight recovery drill; exact pinned tag/commit; preservation and
  reapplication of the inventoried staged/unstaged changes; and proof that no
  Stage 0 or implementation command runs from the old Hermes checkout.
- Exactly one tool schema; no `scroll_search`, `scroll_expand`, `scroll_query`,
  host SQL tool, database handle, unsafe executor, mount, or OS callback
  exposure. `ms.sql_query` accepts only one bounded read-only `SELECT`/CTE and
  rejects writes, admin operations, ATTACH/DETACH, PRAGMA, and multiple
  statements. Monty remains on for every `approvals.mode`; read-only callbacks
  require no approval and a future host-effecting callback obeys current
  per-cell/session approval.
- Namespace persists across feeds and committed compaction in-process, resets
  on reset/end/crash, and `compress()` has zero live-checkout interaction.
- Plugin discovery, non-repository-CWD import, collision with installed Scroll,
  package data/license, optional telemetry, upstream package/evaluation tests,
  provenance-manifest validation, and selected QwenPaw behavioral ports.
- Documentation config/command examples, internal links, runtime prerequisites,
  security/evaluation boundaries, and credential/history redaction in captured
  example output.
- Snapshot/lineage/high-water merge; one-transaction materialization and read
  release under pool saturation, close races, corruption, and automatic versus
  explicit end; skipped `on_turn_complete`; in-place and rotating compaction
  with carried-tail clones, `tail_count`, concurrent rows above the watermark,
  generation-scoped handle invalidation, no duplicate ingestion, and cache
  deletion; transient-marker exclusion and compressed-summary normalization;
  manual compression timeout/discard with zero durable cache mutation; retry
  determinism; incomplete/parallel tool groups; hostile long instructions;
  exact budget overflow/provider retry; fail-open fault injection; and
  reset/undone/deleted exclusion.
- Read-only callback authorizer, statement/work limits, forged/stale/cross-
  lineage navigation, corruption/FTS5/crash/concurrency recovery, path/symlink/
  permissions, redaction, degraded-artifact reporting, positional/named prepared
  bindings, hostile SQL-looking parameter values treated only as data, and
  rejection of oversized, nested, or unsupported parameters.
- The runtime stays display-independent. The desktop-only lane reuses
  `apps/desktop/e2e`, `expectVisualSnapshot`, and the mock inference backend;
  from `apps/desktop`, run `npm run test:e2e:visual`, whose existing script
  supplies `WLR_BACKENDS=headless`, Cage, and the Playwright invocation.
- Desktop Electron Playwright scenarios use the existing mock inference
  backend and seeded history, not a live model. They cover plugin enablement; a
  long session reaching selection/compaction; a visible `scroll_repl` call and
  bounded output; recall and task continuation; cold resume/cache rebuild;
  in-place and rotating compaction; sandbox-denied filesystem/network/process
  attempts; timeout, OOM, crash, namespace-reset, truncation, and error states;
  reset/end cleanup; and every Hermes/ACP approval mode without sandbox bypass
  or spurious approval for read-only callbacks.
- Each desktop scenario has deterministic DOM assertions plus screenshots and
  traces for its meaningful UI states. Visual checks cover readable tool,
  denial, truncation, and state-loss cards; stable tool-call/result pairing;
  no hidden protocol/history leakage; no duplicate reminder/tool cards; and no
  large-session resume jitter. Run `apps/desktop` typecheck/unit tests, focused
  Playwright specs, `npm run test:e2e:visual` under Cage/headless Wayland, and a
  packaged-app smoke test. Because visual diffs may be non-blocking off `main`,
  acceptance requires either a strict target-branch baseline job or explicit
  review of the generated screenshot/diff artifacts; semantic assertions are
  always blocking.

## Mandatory pre-evaluation readiness gate

After all deterministic, focused, upstream, Hermes, and desktop functional
lanes pass, but before any subscription- or API-consuming run, freeze an exact
implementation commit and produce a review bundle containing its diff, test
results, Stage 0 containment evidence, dependency/provenance records, known
limitations, and the credential-free live-evaluation manifest.

A fresh-context `rubber_duck` review must cover the complete integrated diff,
canonical-history/lifecycle correctness, sandbox and callback boundary,
failure/recovery behavior, tests and assertion quality, secret handling, and
evaluation fairness. On-the-fly reviews during implementation are encouraged
but do not replace this checkpoint. Resolve all P0/P1 findings and record lower
severity deferrals with rationale. Re-run affected deterministic evidence after
every correction.

The gate records `GO` or `NO-GO`, the implementation commit, plan and manifest
hashes, reviewer identity, findings/dispositions, test artifact locations, and
the live-model/judge authentication smoke-test result without credentials. Only
`GO` authorizes live-model evaluation. A material code, dependency, sandbox,
model, judge, prompt, dataset, or manifest change invalidates the gate and
requires a focused re-review before affected runs resume.

## Git delivery checkpoints

Use the existing implementation feature branch and authenticated GitHub remote;
never push directly to `main`, rewrite published history, or force-push. This
plan does not authorize creating a pull request.

1. After the mandatory pre-evaluation gate records `GO`, commit the exact
   reviewed implementation, tests, docs, and credential-free manifest; push the
   feature branch; verify the remote commit by fetching it; and record the
   branch, local/remote commit SHA, plan/manifest hashes, and gate artifact. This
   is the immutable pre-evaluation checkpoint.
2. After authorized model-backed evaluation and the final evidence review,
   resolve accepted findings, rerun every invalidated test or review gate, then
   commit and push the final code, docs, manifests, and curated non-sensitive
   results to the same feature branch. Record and fetch-verify the final remote
   commit SHA.

Never commit or push credentials, auth stores, refresh tokens, private dataset
content, raw secret-bearing histories/traces, caches, virtual environments, or
oversized generated artifacts. Publish only reviewed, license-compatible,
redacted evidence. If authentication, authorization, branch protection, or
remote verification fails, stop and report the blocker without weakening remote
controls or changing remotes. A later pull request is a separate user-authorized
action.

## Evaluation and acceptance

Use three evidence tiers:

1. CI runs eight deterministic synthetic histories that cover temporal update,
   conflicting evidence, dispersed aggregation, exact-value recall, parallel
   tool groups, failed/retried tools, cache loss/resume, and corruption/fallback.
2. A frozen stratified integration manifest runs 32 LongMemEval_S items and 16
   BEAM_100K items through the pinned Scroll loaders/judges. Gold answers and
   rubrics remain unavailable to the agent. The manifest pins item IDs, dataset
   revision/license, prompts, judge/model versions, temperature/seed, input and
   output budgets, and all source commits.
3. Full LongMemEval_S and larger BEAM tiers are scheduled, explicitly costed
   evidence before any broader benchmark claim; they are not substituted by or
   compared directly with the paper's published scores.

Separately compare stock Hermes compaction with sandboxed Scroll using the same
model, tasks, and input budgets on 20 fixed long coding trajectories: multi-file
changes, failed/retried tool calls, long build/test logs, manual/automatic
compaction, and resume after cache loss. Use paired stock/plugin executions and
report every absolute/paired delta, upstream-CPython deviation, and sandbox
latency/resource cost. The reference performance host is the existing Contabo
Cloud VPS 6 (6 vCPU, 12 GiB RAM, Ubuntu 26.04 x86_64) using locked uv 0.12.9 and
project-local CPython 3.12.14; warm-selection and rebuild scenarios use a
100K-token canonical history and five repeats per scenario.

The integration passes only if Stage 0 passes; the one permitted tool is
`scroll_repl`; no ambient host capability is reachable; all normal/faulted
selection stays within `input_target`; policy/task/tool-group preservation and
injected recovery are 100%; seeded recall precision and success are at least
95%. For the 20 coding trajectories, 10,000 paired bootstrap resamples must put
the one-sided 95% lower confidence bound for the plugin-minus-stock task-success
difference at or above -5 percentage points; report the interval and raw paired
outcomes. On the named host, history scale, and repeat count, warm selection p95
must be below 500 ms and cold canonical rebuild below 2 s. Focused, upstream,
and relevant Hermes tests must pass on the remote Linux worker. The deterministic
desktop semantic suite and packaged-app smoke test must pass, and visual
artifacts must have no unapproved regression under the target-branch baseline
policy. Visual desktop evidence validates presentation and lifecycle UX only;
headless benchmarks remain the correctness evidence for context retention and
recall.

After model-backed runs, a final evidence review checks paired-run completeness,
failures/exclusions, manifest conformance, statistical calculations, security
or upstream deviations, and reproducibility artifacts before declaring final
acceptance or making benchmark claims.

## Remote Codex prerequisites

- The Context7 plugin is installed and enabled.
- The GitHub plugin is installed and enabled.

## Out-of-scope notes

- Windows compatibility, including platform-specific paths, provisioning, and
  test coverage, is deferred from this Linux delivery.
- Production deployment is out of scope. The disposable VM/account, scrubbed
  environment, no-secret repository, restricted network at the VM/account
  boundary, bounded writable area, and destroy/rebuild procedure remain
  defense in depth around—not substitutes for—the Monty acceptance tests.
- Research RLM harnesses and their REPL implementations as future comparison
  and integration candidates.
- Explore QwenPaw as a separate path and assess adapting it into a full coding
  agent.
- Unifying Hermes's canonical `state.db` transcript and the plugin-owned Scroll
  recall index/cache in one shared SQLite database is deferred future work. V1
  uses `CanonicalHistorySnapshot` and a separate rebuildable plugin cache;
  continuity across physical sessions in one logical lineage does not imply
  shared storage with Hermes.
