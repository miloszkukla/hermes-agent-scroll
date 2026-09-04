# Scroll deterministic evaluation lane

This lane checks eight synthetic canonical-history fixtures without a model,
network access, account, or credential. It is not a benchmark claim: it proves
that the read-only callback surface can recover the seeded facts after the
history projection is materialized.

Run it through the project test runner:

```bash
scripts/run_tests.sh tests/evals/test_scroll_deterministic.py
```

`manifest.json` is the credential-free manifest. It must not be overwritten
or used as authorization for a live run.

`longmemeval.py` and `beam.py` are thin value-only ingest adapters for the
pinned upstream dataset shapes. They normalize session dates and retain only
the task haystack in a `CanonicalHistorySnapshot`; neither accepts gold answers
or creates a source SQLite database.

`upstream_adapter.py` projects upstream probes to `id`, `type`, and `question`
before they can reach Hermes, then serializes Hermes responses in the pinned
upstream judge shape. It excludes rubric and gold-answer fields. The source
drift runner and its corpus boundary are documented in
[`plugins/context_engine/scroll/evidence/UPSTREAM-EVALUATION-DRIFT-LANE.md`](../../plugins/context_engine/scroll/evidence/UPSTREAM-EVALUATION-DRIFT-LANE.md).

`live-manifest.template.json` and `coding-live-manifest.template.json` are
deliberately non-runnable. Copy one only after the pre-evaluation review, fill
it without credentials, and validate it with `validate_live_manifest()` before
a driver opens a provider connection. The validator rejects incomplete fields,
unequal stock/plugin settings, and credential-shaped keys.

`paired_runner.py` is the credential-free orchestration seam shared by the
live drivers. It validates the approved manifest, runs at most four isolated
workers concurrently, preserves deterministic stock/Scroll row order, caps
every agent and judge call against token budgets, exposes only
`id`/`type`/`question` to an agent executor, and retains answer digests plus
scores instead of raw histories, answers, or gold.

## Authorized live lanes

`hermes_live.py` runs the frozen 32-item LongMemEval_S and 16-item BEAM_100K
selection through Hermes's stock and Scroll arms. It executes the pinned
upstream Scroll judges in the separately locked source environment; the agent
never receives a gold answer or rubric. `coding_live.py` runs the separate,
fixed 20 coding trajectories in fresh workspaces. Those tasks start failing and
use an objective local `pytest` verifier rather than a memory-benchmark judge.
They cover automatic compaction, manual selection, and cold resume after a
Scroll-cache loss, with multi-file repairs, failed/retried tool context, and
long build/test-log history in each trajectory. Every trajectory has a
minimum 100K-token rough canonical history, includes two actual durable
terminal call/result groups (one failed and one retried), and runs five paired
repeats. The coding report measures manual host-compaction selection and
post-cache-loss agent construction separately from provider execution; its p95
thresholds therefore cover only the required selection/rebuild operations.

Both drivers require an authenticated ChatGPT Codex OAuth credential in the
caller's Hermes home at run time. The parent alone resolves and refreshes the
OAuth store, then gives each worker a short-lived access-token lease with enough
life for its bounded subprocess. Workers and judges never receive `auth.json` or
a refresh token; the worker deletes its one-use lease file before model tools
begin. Runtime/job directories are owner-only and the one-use job file is
owner-read/write only. Coding workers run with a sanitized environment, an empty
sandboxed `/home`, and explicit read-only system/source mounts plus their
writable job tree. Raw corpus histories, model answers, generated workspaces,
and provider traces stay below the ignored runtime root. A durable report has
only manifest/hash metadata, objective scores, usage, and answer digests.

After a recorded `GO`, run the reviewed commands from the repository root:

```bash
python -m evals.scroll.hermes_live \
  --manifest plugins/context_engine/scroll/evidence/live-memory-manifest.json \
  --longmemeval .scroll-runtime/evaluation/longmemeval/data/longmemeval_s \
  --beam-chats .scroll-runtime/evaluation/beam/chats \
  --scroll-source /tmp/scroll-upstream.HP8snA \
  --runtime-root .scroll-runtime/live-memory \
  --output .scroll-runtime/reports/live-memory.json

python -m evals.scroll.coding_live \
  --manifest plugins/context_engine/scroll/evidence/live-coding-manifest.json \
  --runtime-root .scroll-runtime/live-coding \
  --output .scroll-runtime/reports/live-coding.json
```

The memory manifest pins the exact Scroll source revision and the upstream
judge model. Both Hermes arms, every auxiliary compression call, and every
judge call must use the declared OpenAI Codex model; any other provider or
model fails the run. The coding manifest declares `none-objective-verifier` as
a non-model judge. Any changed source, model, prompt, dataset, task set,
budget, seed, parallelism, or manifest requires a new review gate and a new
paired run. Both live drivers fail closed if the candidate checkout, the pinned
Scroll judge source, or the tracked LongMemEval/BEAM source trees have changed;
the LongMemEval corpus file is additionally SHA-256 pinned and the judge
environment must import `scroll_eval` from the pinned source checkout.
