# Scroll model-access preflight

## Status

**No manifest-backed model run has started.** This record applies the separate
[`EVALUATION-ERRATA.md`](../../../../EVALUATION-ERRATA.md) advisory before the
first model-backed lane. It is not itself a live manifest or permission to run
an unfrozen model/judge pair.

## Evidence inspected

- `PLAN.md` distinguishes deterministic, fixture-backed lanes from
  model-backed LongMemEval, BEAM, and paired coding trajectories.
- The pinned Scroll source's `evaluation/scroll_eval/runner.py` constructs
  OpenAI-compatible and (when its endpoint contains `dashscope`) DashScope
  clients. Its `configs/longmemeval.yaml` and `configs/beam.yaml` leave the
  endpoint and model as environment placeholders; their `thinking: true`
  comments are DashScope-specific options, not benchmark requirements.
- The pinned LongMemEval judge creates an OpenAI-compatible chat-completions
  client and defaults its judge model to the agent model. The pinned BEAM judge
  does the same, including several concurrent judge calls for some probes.
- The retained `evaluation/tests/` lane uses mock/stub models; its runner's
  API-key-shaped value is a test-only constructor stub and never reaches a
  provider. The local Scroll ingest, adapter, deterministic, Stage 0, cache,
  and desktop mock-inference tests likewise make no model call.

## Lane classification

| Lane | Model access | Recorded decision |
| --- | --- | --- |
| Stage 0; plugin/host tests; deterministic fixtures; vendored package tests; upstream evaluation drift tests; desktop mock/visual tests | None | Credential-free evidence only. Do not authenticate. |
| LongMemEval_S and BEAM_100K paired benchmark | An agent-under-test model and an LLM judge are both required for the intended metric. | `evals.scroll.hermes_live` runs Hermes, keeps gold outside the agent process, and invokes the pinned upstream judge only after the response. Do not reuse the upstream Scroll reference-agent loop to test Hermes. |
| Paired coding trajectories | An agent-under-test model is required. Task success also needs the specified objective verifier or a separately reviewed scorer. | `evals.scroll.coding_live` freezes 20 generated failing workspaces and scores only their local `pytest` result; it does not infer a memory judge. |

## Provider and model decision for a future reviewed manifest

The upstream defaults do **not** require Qwen, DashScope, or any particular
provider. A meaningful Hermes comparison instead requires the same frozen
agent provider, exact agent model, auth mode, prompt, tool surface, seed,
temperature, context/input and output budgets, and rate-limit conditions for
both stock and Scroll arms. The chosen agent model must support the Hermes tool
surface used by the evaluated driver and the configured context budget.

The LongMemEval and BEAM source judges use OpenAI-compatible chat-completions
requests. The manifest must name the exact judge model, its provider and auth
mode, endpoint compatibility, temperature, concurrency, and any fact-alignment
mode. A separate judge provider is permitted only when those fields are made
explicit in the reviewed manifest and both arms use the same frozen judge; it
must not be silently represented by the current single `provider` field.

Before a live run, freeze the provider/model and authentication method in each
credential-free manifest, record an authentication smoke result without a
credential, and require the pre-evaluation `GO`. The memory lane also freezes
the compatible upstream judge model; the coding lane records its objective
local verifier. If either provider path is unavailable, report that affected
lane as blocked; do not substitute a model or claim an upstream comparison.
