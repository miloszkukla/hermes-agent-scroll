# Scroll evaluation boundary

The deterministic lanes require no model credential: Stage 0, snapshot/cache,
adapter, upstream-drift, and desktop mock-inference tests. Do not authenticate
or export credentials to run them.

The eight synthetic callback-recall cases and their credential-free manifest
live in [`evals/scroll`](../../../evals/scroll/README.md). Run them with
`scripts/run_tests.sh tests/evals/test_scroll_deterministic.py`; their results
are not a substitute for a reviewed live-model manifest.

Run the local deterministic gate from the repository root with:

```bash
scripts/run_tests.sh tests/hermes_state/test_canonical_history_snapshot.py tests/run_agent/test_canonical_history_handoff.py tests/plugins/test_scroll_cache.py tests/plugins/test_scroll_context_engine.py tests/plugins/test_scroll_plugin_discovery.py tests/plugins/test_scroll_documentation.py tests/plugins/test_scroll_stage0_monty.py tests/evals/test_scroll_deterministic.py tests/evals/test_scroll_longmemeval.py tests/evals/test_scroll_beam.py tests/evals/test_scroll_hermes_live.py tests/evals/test_scroll_coding_trajectories.py tests/evals/test_scroll_live_manifest.py tests/evals/test_scroll_paired_runner.py tests/evals/test_scroll_upstream_adapter.py
scripts/run_tests.sh plugins/context_engine/scroll/vendor/tests
```

These commands are credential-free. Store only redacted reports and hashes in
the repository; do not put histories, provider output, credentials, or account
identifiers in a test artifact.

The separately checked-out pinned upstream evaluation drift lane is run with
`bash scripts/run_scroll_upstream_evaluation_tests.sh /path/to/Scroll`. Its
source-lock setup, corpus exclusions, and result are recorded in
[`UPSTREAM-EVALUATION-DRIFT-LANE.md`](evidence/UPSTREAM-EVALUATION-DRIFT-LANE.md).
The value-only ingest and judge-shape adapter accepts only agent-visible probe
fields and Hermes answers; it never puts gold/rubric fields into model context.
[`MODEL-ACCESS-PREFLIGHT.md`](evidence/MODEL-ACCESS-PREFLIGHT.md) records why
this retained upstream lane remains credential-free and what the future live
agent and judge lanes actually require. Its DashScope/Qwen source examples are
not a required model choice.

Before any model-backed lane, create a reviewed manifest that freezes the
agent model, judge model, provider/auth mode, seed, temperature, budgets,
dataset revision and item IDs, cost ceiling, source commits, and stock/plugin
pairing. Keep credentials, raw histories, private datasets, caches, traces,
and account identifiers out of the repository and Monty.

Only a recorded pre-evaluation `GO` that names an implementation commit,
manifest hash, Stage 0 evidence, reviewer, and credential-free smoke result
authorizes a live run. Any material implementation, dependency, model, judge,
prompt, dataset, or manifest change invalidates that decision.

`evals/scroll/live-manifest.template.json` and
`evals/scroll/coding-live-manifest.template.json` are intentionally non-live.
Their validator requires a full reviewed commit, dataset revisions/item IDs,
identical stock/plugin settings, model and budget identities, and a positive
cost ceiling; it rejects credential-shaped fields. Filling or validating a
template is not authorization to authenticate or contact a provider.

For a live run, use one frozen manifest revision for both stock and Scroll
arms, apply the same item IDs, prompts, provider/model identities, seed,
temperature, and token budgets, and enforce its cost ceiling before launch.
Run paired arms together; an implementation, runtime, source, prompt, dataset,
provider, judge, or manifest change invalidates the affected pairs and requires
a reviewed restart. Record exclusions, retries, raw paired outcomes, latency,
and the manifest hash so the final reviewer can distinguish a completed result
from an interrupted or incomparable run.

The reviewed live executors are `python -m evals.scroll.hermes_live` for the
LongMemEval_S/BEAM pair and `python -m evals.scroll.coding_live` for the 20
fixed coding trajectories. Their exact commands, corpus paths, ignored-runtime
layout, source-judge pin, and objective coding verifier are in
[`evals/scroll/README.md`](../../../evals/scroll/README.md). The durable
reports retain only manifest metadata, scores, usage, and answer digests;
never publish raw workspaces, histories, model output, credentials, or traces.
