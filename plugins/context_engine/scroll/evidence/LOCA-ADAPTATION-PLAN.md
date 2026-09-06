# Hermes LOCA adaptation preparation

This is a preparation for a **Hermes LOCA adaptation**, not a reproduction of
the Scroll paper's LOCA result. The paper used QwenPaw/AgentZero and a broader
`repl_exec`/environment-tool surface; those adapter and task-package pins are
not public. The public [LOCA-bench](https://github.com/hkust-nlp/LOCA-bench)
source is nevertheless sufficient to build a clearly labelled Hermes-native
comparison against the 75-state `final_128k_set_config.json` or
`final_256k_set_config.json` matrix.

`evals/scroll/loca_live.py` freezes that matrix and provides the orchestration
contract. It is intentionally inspection-only until the adapter exists:

```bash
python -m evals.scroll.loca_live --inspect \
  --loca-source /path/to/LOCA-bench --context-size 128k
```

Before a live run, the adapter must do all of the following for every LOCA
state:

- Materialize the task exactly once below its task root. The runner hashes the
  immutable base snapshot itself, and puts
  the agent workspace, MCP databases, ports, Hermes home, logs, and process
  group under the per-job runtime root.
- Clone that base snapshot separately for stock and Scroll. Both arms receive
  the same LOCA tools and task instruction. Ground truth and the native
  verifier remain outside the agent-readable filesystem.
- Start both agents in the exact `agent_workspace`, make that path explicit in
  the stable system prompt, and require literal completion of quantified task
  requirements. When LOCA provides its task-scoped Python executor, direct
  both arms to use it for exhaustive structured-data work and artifact
  validation rather than sampling; its task-local `../local_db` input may be
  inspected but never modified. Local databases are inspected with read-only
  standard-library `sqlite3`; artifact units must match their headers. The
  pinned LOCA environment must provide its required `uv` launcher, validated
  during structural preflight. Require the Scroll arm to call `scroll_repl`
  before completion. This is a Hermes tool-policy ablation, not a claim that
  QwenPaw used the same policy.
- Stop Hermes and MCP services before invoking LOCA's native final-state
  verifier. Persist only a result with the score plus trajectory, final-state,
  and verifier digests after that verifier succeeds.
- Use the runner's flat global worker pool. `setup_workers` bounds state
  materialization; `job_workers` bounds all stock/Scroll jobs globally, rather
  than assigning a nested pool per task.
- Resume only an atomically recorded `status: completed` result whose semantic
  provenance matches: claim scope, task configuration, initial snapshot, plan,
  arm, and verifier. The runner SHA is attempt metadata, recorded in the report
  but not a checkpoint compatibility gate. An incomplete or corrupt job restarts from the
  immutable snapshot; mid-trajectory continuation is intentionally unsupported.

The runtime must also freeze the public LOCA checkout commit, configuration
hash, Hermes/Scroll/adapter/prompt/tool-schema hashes, environment image and
dependency-lock hashes, model/provider/authentication/billing/reasoning
settings, timeouts, and worker limits. The scheduler/runner SHA is recorded as
diagnostic attempt metadata, rather than causing compatible task checkpoints to
restart. A report is written only after the
complete paired grid finishes; successful per-job checkpoints remain available
for a later resume if any job fails. Starting a new attempt retires an existing
active report to a content-addressed `.previous-…` filename first, so a failed
rerun cannot be mistaken for the last successful run.
