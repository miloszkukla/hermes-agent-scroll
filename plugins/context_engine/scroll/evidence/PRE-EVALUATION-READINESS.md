# Scroll pre-evaluation readiness

## Current status

**GO for the refreshed ChatGPT Codex OAuth coding candidate.** The task owner
replaced OpenRouter with ChatGPT Codex OAuth and authorized up to four isolated
workers. A partial coding run was excluded after an absolute `cd` escaped its
task workspace; the replacement uses a Bubblewrap read-only checkout boundary.
The candidate, frozen coding manifest, and independent focused GO are recorded
in [CHATGPT-OAUTH-PARALLEL-REVIEW-2026-09-04.md](CHATGPT-OAUTH-PARALLEL-REVIEW-2026-09-04.md).

## Historical Flex decision

**GO for the frozen Flex-tier candidate.** The exact implementation candidate,
credential-free manifests, source and corpus pins, and prior independent review
are recorded below. The task owner authorized the OpenRouter credential in
`/home/codex/.hermes/.env` on 2026-09-04. The first stock worker reached its
auxiliary compression call but failed before the agent turn because Hermes chose
the incompatible Codex Responses transport for the frozen seed. A subsequent
Chat Completions retry completed one coding worker, but its output exceeded the
then-undersized aggregate cap and its terminal task CWD was not isolated. Both
incomplete traces are excluded; the reviewed replacement candidate below forces
Chat Completions, registers the task workspace, and has no accepted paired
result yet. The task owner subsequently selected OpenRouter Flex; the
default-tier coding run was stopped after one result and is also excluded. The
replacement candidate requests Flex for agent, auxiliary-compression, and judge
calls; the fresh independent review cleared `10869fc0bb736bff89ce365d0d79f13831fd4d21`
before restarting.

## Frozen inputs at this checkpoint

| Item | Value |
| --- | --- |
| Hermes base | `29112bef099274229cadff79cdff7bf7b99c4b77` (`v2026.8.31`) |
| Scroll source | `313077708ea105cc79bf0a997338e14dae916f8c` |
| Plan SHA-256 | `7031dc9351254dd2846f1471f958b32b9b1ecbca112352d3ca047260a5cd8210` |
| Credential-free manifest SHA-256 | `b8356f7971b9a0c16d33f564c84e39d194fc55d2f6308de4f55a5448ab9f536e` |
| Stage 0 report SHA-256 | `295aacf7cbadcd197d5b82bd70b6a4d5edb27049099735302acb9541413dc7d3` |
| Evaluation advisory SHA-256 | `f4fe4183547b18a411e54d2e6c5c9d3b5e7f6ae87f96cd747a499953de0e7939` |
| Implementation commit | `10869fc0bb736bff89ce365d0d79f13831fd4d21` |
| Memory live-manifest SHA-256 | `6b4c692d94ed5a0dfda5410c00b99fbbd39e3de7000332b9de89e27343b03ce4` |
| Coding live-manifest SHA-256 | `48d88ebaa11cf64ea1996f562bf2fc03b197f5af54c4836dcebdc19bbe6d14a6` |
| OpenRouter tier / accounting rate | `flex` / `$0.10` input, `$0.60` output, and `$0.01` cache-read per million tokens |
| Memory/coding cost ceilings | `$15.00` / `$25.00` |

## Passing credential-free evidence

- Stage 0 Monty containment and compatibility: 18 tests, including the
  deployed bootstrap and `MontyScrollRepl` wrapper path.
- The Stage 0 attestation was revalidated against its current harness after
  detecting a stale earlier harness hash; its companion checksum verifies the
  report now recorded above.
- The complete focused Scroll/Hermes matrix — canonical snapshot, adapter and
  cache, deterministic selection/truncation, boundary-index lifecycle,
  pending-suffix merge, non-repository-CWD discovery, documentation,
  LongMemEval/BEAM adapters, deterministic fixtures, package-record integrity,
  live-manifest validation, steer persistence/projection, and SessionDB
  regressions, recursive credential rejection, and paired-run orchestration —
  passed: 399 tests.
- `scripts/bootstrap_scroll_runtime.sh --verify-only` digest-verified and
  materialized the locked uv and CPython archives in this checkout and from an
  otherwise empty temporary checkout layout without creating a virtualenv.
- Existing concurrent-fork compression regression paths: 48 tests.
- Unmodified Scroll upstream CPython drift lane, including eviction-index
  simulation: 75 tests. This is not Monty-containment evidence.
- Desktop typecheck and lint passed. The full UI-unit runner passed 6,809
  tests with zero failures or errors (temporary JUnit verification report).
- The complete desktop Playwright suite passed under Xvfb (76 tests) and the
  final Cage/headless-Wayland rerun passed all 83 currently collected tests.
  The live-correction session-switch case,
  formerly the sole failure, also passed six repeated parallel executions after
  durable correction metadata was projected during REST history hydration. One
  post-change Cage run recorded a warm-resume fixture setup interruption before
  any model call (`status: interrupted`, `calls: 0`); the case passed alone,
  and an 18-run two-worker warm-resume/large-session stress run passed. A fresh
  exact `npm run test:e2e:visual` Cage rerun then completed with
  `test-results/.last-run.json` reporting `passed` and no failed tests. The
  six-run parallel correction/session-switch stress test also passed after the
  final warm-cache recovery narrowing.
- Dedicated deterministic Scroll desktop scenario under native headless Wayland:
  9 tests passed, covering a bounded successful call, a namespace seeded before
  a desktop/backend restart then rejected and recovered from canonical history,
  generation-bound stale handles after both in-place and rotating compaction,
  visible host-filesystem/network/process denial without approval cards, reset
  cleanup, manual/smart/off approval modes, and timeout/OOM namespace resets
  with canonical-history recovery, including an E2E-only real worker `SIGKILL`
  and canonical-history recovery through the replacement worker. It produced a
  visual capture but no target-branch baseline comparison.
- The final fresh-context technical review recorded no P1/P2 findings after
  the lifecycle, SQL-containment, and reset-isolation regressions were added;
  see [FRESH-CONTEXT-REVIEW-2026-09-04.md](FRESH-CONTEXT-REVIEW-2026-09-04.md).
- Packaged Linux app smoke under Xvfb: 6 tests passed.
- `ruff check` and `git diff --check` passed. Ruff emitted the existing
  malformed `# noqa` warning at `run_agent.py:108`; it reported no violations.
- [PRECOMMIT-REVIEW-BUNDLE.md](PRECOMMIT-REVIEW-BUNDLE.md) pins the complete
  reviewed candidate diff and credential-free delivery-file hashes for this
  GO-eligible implementation commit.
- The final live-executor review found no actionable P0/P1/P2 on
  `f86f3bb2f3f3a6de517b82382eb17e30277eb763`; it specifically rechecked
  durable host compaction, 100K-token histories with valid failed/retried
  terminal groups, fail-closed source/corpus pinning, and source-CWD judge
  imports. See [FRESH-LIVE-EXECUTOR-REVIEW-2026-09-04.md](FRESH-LIVE-EXECUTOR-REVIEW-2026-09-04.md).
- The transport amendment was independently reviewed with no actionable
  P0/P1/P2 on `c17b49e79c31632802433800eb46d4b17463449c`; both arms now
  explicitly use seeded OpenRouter Chat Completions. Its terminal-isolation
  follow-up was independently reviewed with no actionable P0/P1/P2 on
  `6fc652d37c78d0c598cb11b11de12bfe2359ea3b`: each coding task now registers
  its workspace with the task ID, and the aggregate output cap is 65,536 tokens
  while each auxiliary call retains its 4,096-token cap.
- The Flex-tier amendment is intentionally not covered by the preceding review;
  its first review returned a P1 because cache-read usage was omitted from the
  cost ceiling, and its second review found that auxiliary accounting failures
  were swallowed and raw worker totals were trusted. The next review found
  malformed judge usage defaulted to zero. The replacement candidate separately
  accounts main-agent, auxiliary-compression, and judge cache reads under a
  frozen 1,000,000-token budget, captures auxiliary accounting errors, requires
  complete positive judge usage, and recomputes costs from frozen rates before
  enforcing the ceiling. The fresh complete candidate-and-manifest review
  cleared `10869fc0bb736bff89ce365d0d79f13831fd4d21` with no actionable P0/P1/P2.

## Completed gate items and execution limits

1. The final 83-test desktop E2E suite is green under Cage/headless Wayland.
   The base branch has no matching `scroll-repl` scenario or target image, so a
   pixel-diff baseline cannot exist for this new surface. The task owner
   explicitly approved the base-branch interpretation and the direct generated
   artifact review recorded below. Semantic assertions remain blocking.
   The pinned upstream `e2e-desktop` Actions job is disabled by the caller's
   literal `false &&` gate, so GitHub Actions supplies no baseline for this
   version; the pinned-SHA CI run 33430852764 has no jobs. Ubuntu's packaged Cage
   0.2.1 aborts during Xwayland teardown in this environment, so the current
   focused native-Wayland lane uses a local Cage 0.2.1 build with Xwayland
   disabled. The dedicated desktop scenario covers a successful mock-backed
   tool card, cold-cache rebuild, both compaction modes/stale-handle,
   denied filesystem/network/process recovery, reset cleanup, all configured
   approval modes, timeout, watchdog worker replacement, and OOM states.
2. The pinned Scroll `evaluation/tests/` non-corpus drift lane now passes
   (133 passed, 1 skipped) in a separately locked source checkout; see
   `UPSTREAM-EVALUATION-DRIFT-LANE.md`. The upstream BEAM and Terminal-Bench
   local corpora are absent. The credential-free paired runner validates
   ordering, token/cost caps, model-probe redaction, and answer digests, but
   `evals.scroll.hermes_live` supplies a source-locked Hermes executor and
   judge boundary, and `evals.scroll.coding_live` supplies 20 fixed objective
   coding trajectories. The reviewed manifests freeze the 32/16 memory set and
   the complete 20-trajectory coding set; no paired live result exists yet.
   The eight local synthetic fixtures remain deliberately narrower and cannot
   stand in for either live lane.
3. An independent fresh-context technical review completed with no P1/P2
   findings after the deployed Stage 0 path, generation-bound handles, bounded
   failure fallback, recursive manifest validation, tracked bootstrap, resumed
   snapshot publication, desktop lifecycle coverage, and SQL projection bounds
   were repaired. That review predates the live executors and is superseded for
   gate purposes; the subsequent fresh complete-diff live-executor review is
   recorded above and cleared the candidate.
4. The task owner authorized OpenRouter access, selected Flex, and selected the
   base branch as the visual reference. The pending manifests pin
   `openai/gpt-5.6-luna`, Flex, seed, budgets, pricing, and all source/dataset
   inputs.

This GO authorizes only the recorded commands and frozen manifests.
Any material source, dependency, prompt, dataset, model, task set, or manifest
change invalidates it and requires another candidate review.

## Visual artifact disposition

On 2026-09-04, the deterministic `scroll-repl` Playwright scenario passed and
its `scroll-repl-complete-actual.png` artifact was inspected directly. The
trigger, visible Scroll REPL label, bounded completion text, session identity,
and composer were legible; no hidden protocol/history content, duplicate tool
card, clipped text, or unintended approval UI was visible. No target-branch
baseline exists, so this is an explicit implementation-side artifact review,
not the independent fresh-context review required for GO.

## Current local reruns

The current worktree was revalidated on 2026-09-04 after the Scroll
in-place/rotating-compaction lifecycle, sandbox-denial/recovery,
resource-limit/watchdog-replacement, reset, approval-mode, and cold-restart
namespace-reset desktop additions:

- The new live-evaluation boundary tests passed: 77 assertions across the
  documented deterministic gate, including source-revision and prompt-hash
  checks, gold-free LongMemEval/BEAM loading, shared agent/judge cost caps,
  and the 20 fixed objective coding trajectories. `ruff`, Python compilation,
  both live-runner `--help` commands, `git diff --check`, Stage 0 (18/18), and
  vendored upstream Scroll tests (75/75) also passed after that addition.

- `npm run typecheck && npm run lint` exited zero. Lint reported 127 existing
  warnings and no errors.
- `npm run test:ui` passed 6,812 tests with zero failures or errors in a
  JUnit report; `npm run
  test:desktop:platforms` passed 1,977 tests with 6 expected skips.
- The focused Scroll Playwright scenario passed all 9 tests under
  `cage-no-xwayland`, including a seeded namespace rejection after a true
  desktop/backend restart, persisted-canonical-history recovery, rotating and
  in-place compaction, reset cleanup, configured approval modes, and visible
  denial/timeout/watchdog-replacement/OOM error cards. The worker-crash branch
  sends the actual worker `SIGKILL` only when its E2E environment gate is set.
  The focused gateway-server regression suite also passed: 628 tests.
- The final post-review Scroll Python subset passed 51 tests across canonical
  history, plugin initialization/lifecycle, CLI resume/branch handoff,
  recovered compression-child first recall, SQL source/query bounds, paired
  runner, and live-manifest validation. The documented clean-environment Stage
  0 command separately passed 18 tests.
- The focused Scroll/Hermes Python matrix passed 1,026 tests across 20 files,
  including the plugin, canonical-history, gateway, steering, lifecycle, and
  deterministic evaluation surfaces.
  The full Xvfb desktop suite initially had 72 passes, 5 expected skips, and one
  failure in the unrelated `unread-dot-restart` case. That test passed alone,
  and an immediate clean full rerun passed 73 tests with 5 expected skips in
  seven minutes. The current final Cage/headless-Wayland run passed all 83
  collected tests; its former unread selector targeted a drag-only span and
  now resumes the owning row.
- A final `npm run typecheck` passed, the focused Scroll desktop scenario
  passed all 9 tests under `cage-no-xwayland`, and `git diff --check` passed.
- The focused Scroll plus unread-restart E2E subset passed under
  `cage-no-xwayland`. A complete 83-test Cage/headless-Wayland run then had
  one timeout in the unrelated zoom-preservation route test; that test passed
  2/2 in a clean isolated run and the next complete rerun passed all 83
  collected tests. The `unread-dot-restart` regression now waits for session
  B's busy-to-idle edge, requires the lone marker on session A, and resumes
  that exact row before checking persistence.
- `scripts/bootstrap_scroll_runtime.sh --verify-only` reconfirmed the locked
  uv/CPython artifacts and the exact CPython 3.12.14, `cpython-312`, glibc
  2.43, and SQLite 3.53.1 runtime. The Stage 0 Monty harness then passed 18/18.
- The documented credential-free Scroll/Hermes deterministic gate passed
  70/70, and the vendored upstream package-drift lane passed 75/75.
- A fresh separately locked checkout of the pinned Scroll source completed the
  documented non-corpus evaluation drift lane: 133 passed, 1 expected BEAM
  migration skip, and one benign SciPy small-sample warning.
- The packaged desktop smoke lane passed all 6 tests under
  `cage-no-xwayland`.
- `npm run build` completed successfully, regenerating the production renderer,
  Electron main/preload bundles, and staged native dependencies.

A strict target-branch visual baseline remains unavailable.
