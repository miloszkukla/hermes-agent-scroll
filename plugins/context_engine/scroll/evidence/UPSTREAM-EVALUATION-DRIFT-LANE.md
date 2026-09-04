# Pinned upstream evaluation drift lane

## Source and setup

The source tree was cloned from `https://github.com/niceIrene/Scroll.git` and
checked out detached at `313077708ea105cc79bf0a997338e14dae916f8c`. Its own
`uv.lock` was used unchanged:

```bash
cd /path/to/Scroll
HERMES_ROOT=/path/to/hermes-agent-scroll
UV_PYTHON="$HERMES_ROOT/.venv/bin/python" \
  "$HERMES_ROOT/.uv/tools/uv-x86_64-unknown-linux-gnu/uv" \
  sync --locked --all-packages --all-groups --extra beam
```

The resulting isolated evaluation environment installed 138 packages from the
pinned source lock. It is separate from Hermes's `.venv`, uses no real model
credential, and does not exercise the Hermes adapter.

## Commands and observations

The repository runner validates the detached source commit before executing
the unmodified upstream tests:

```bash
bash scripts/run_scroll_upstream_evaluation_tests.sh /path/to/Scroll
```

On 2026-09-03, and again on 2026-09-04, the full upstream suite collected 141 tests. It reported 133
passes, one expected BEAM migration skip, and seven environmental failures:

- Four BEAM event-ordering judge tests needed the source's optional `beam`
  extra (`scipy`); they passed after the locked extra was installed.
- One stubbed runner-dispatch test needs an API-key-shaped but non-secret value
  because the source lock's OpenAI client enforces client construction even
  though the test makes no provider call. The runner supplies a fixed test-only
  value instead of reading user credentials.
- The remaining two source tests require untracked local task corpora: migrated
  BEAM tiers (`local-tasks/beam`) and Terminal-Bench 2.1
  (`local-tasks/terminal-bench-2.1`). Those corpora are not present in the
  pinned source checkout and were not fabricated.

With the two corpus-dependent source test files excluded, the remaining
dependency-complete upstream suite passed unchanged:

```bash
bash scripts/run_scroll_upstream_evaluation_tests.sh /path/to/Scroll \
  --ignore=evaluation/tests/test_beam_cli.py \
  --ignore=evaluation/tests/test_configs.py
```

Result: **133 passed, 1 skipped**, with one benign SciPy small-sample warning.

## Remaining boundary

This is an upstream drift result only. It is not evidence that Hermes's
value-only snapshot adapter is equivalent to Scroll's file-backed
`HistoryStore`, and it is not a model-backed LongMemEval or BEAM result. The
Hermes value-only loader and result-shape adapter live in
`evals/scroll/{longmemeval,beam,upstream_adapter}.py`; they keep rubric/gold
fields out of model-visible input. A live Hermes model driver and the missing
local corpora remain pre-evaluation requirements.
