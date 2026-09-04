# Final live-evaluation evidence — 2026-09-04

## Status

**PENDING independent final evidence review.** This record preserves the
completed live lanes and distinguishes their evidence from final acceptance.
It makes no benchmark-performance or paper-equivalence claim.

## Frozen inputs and reports

| Item | Value |
| --- | --- |
| Current evidence commit | `425280089546f26fdf2e2e143249082ae2b94da9` |
| Coding implementation commit | `5d8cd7a0ff7c3a39b824a7eea646dc57ba00f2a5` |
| Coding manifest digest | `db35ade09f204c0ca4e014ad58ae1bc5216e476da312836db71cff9493487fd4` |
| Coding report SHA-256 | `9e31ce9087d133d2a021fb1ce02d569bd04d0e9c9a0b6fe8db735d69090c7ece` |
| Memory implementation commit | `8c32e5e22252c54a39cd1df415d0cbe04bb67774` |
| Memory manifest digest | `343b3169f912a5426ddceaadd6db7d1a814af2d2e84735a39133addc3c8387d9` |
| Memory report SHA-256 | `5463a530fa1b7cdaf1d971d839cfcf588dfe513e1925bc6d9a5875caec949dd1` |

The non-sensitive raw reports remain ignored runtime artifacts at
`.scroll-runtime/reports/live-coding.json` and
`.scroll-runtime/reports/live-memory.json`. They contain no raw benchmark
histories, prompts, model responses, gold answers, credentials, or auth data.

## Completed coding lane

The coding report has 200 rows: 100 stock, 100 Scroll, five repeats across all
20 fixed trajectories. It reused 82 independently attested r4/r5 rows and ran
the remaining 118 fresh under the schema-v4 3,000-second host,
3,300-second-worker envelope. Every task/repeat has both arms; no outer timeout
or evaluator-level retry occurred.

| Gate | Result |
| --- | --- |
| Paired task-success lower 95% bound | `0.0` (passes the `>= -0.05` gate) |
| Stock / Scroll task-success mean | `1.0` / `1.0` |
| Cold cache-loss rebuild p95 | `0.367242 s` (passes the `< 2 s` gate) |
| Reported manual host-compaction p95 | `1.055644 s` (does not pass the `< 0.5 s` gate if this broader operation is the acceptance metric) |

The current `scenario_latency_seconds` timer starts before
`AIAgent._compress_context()` and therefore includes host-thread scheduling,
configuration lookup, commit-fence and SessionDB bookkeeping as well as the
pure Scroll selection. It is a useful end-to-end host-compaction cost, but it
is broader than the plan's named warm-selection operation. The report must not
be relabelled or normalized after the fact.

For an operation-scoped check, the locked `ScrollContextEngine.compress()` path
was warmed, then run across the six manual-compaction histories five times each
(30 samples, every history at least 108,241 rough tokens) with four concurrent
workers. The p50 was `0.000229403 s`, p95 was `0.000389821 s`, and maximum was
`0.000504272 s`; each selected ten messages. This is the pure deterministic
selection invoked by manual compaction and it passes the plan's 500 ms
warm-selection limit. The final reviewer must explicitly decide whether the
plan means this operation-scoped metric or the broader host-compaction timer;
the two values are intentionally both retained.

## Completed memory lane

The memory report has all 96 expected arms (48 stock and 48 Scroll) with valid
agent and judge usage. Aggregate scores were `30.5804/48` stock and
`21.4991/48` Scroll. This result does not support a Scroll memory-performance
claim and is not compared with the paper's QwenPaw/backbone-specific published
scores. It remains complete evidence, not an excluded or normalized run.

## Final-review checks required

The independent reviewer must verify paired-row completeness and source/manifest
conformance; bootstrap and Stage 0 provenance; task-success and percentile
calculations; the two latency scopes above; resume attestations; known
model/provider, sandbox, or upstream deviations; report redaction; and whether
the plan's final acceptance conditions are met. Any accepted correction that
changes implementation, prompt, data, manifest, or metric semantics requires
the affected evidence and review gate to be rerun.
