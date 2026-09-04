# Test and source provenance

| Material | Source | License | Local handling |
| --- | --- | --- | --- |
| `vendor/scroll_context/` | `niceIrene/Scroll` `313077708ea105cc79bf0a997338e14dae916f8c` | Apache-2.0 | Package-relative import patch only; never imported by the Monty adapter. |
| `vendor/tests/` | Same Scroll commit, `tests/` | Apache-2.0 | Retained unchanged as an upstream CPython drift lane; adjacent test-only `conftest.py` resolves its vendored import root. It is not evidence of Monty containment. |
| `eviction_index.py` | Scroll `scroll_context/_runtime/index.py` at `313077708ea105cc79bf0a997338e14dae916f8c` | Apache-2.0 | Clean-room value-only port of the level-capped carry/collapse map. It receives only immutable canonical rows and has no persistence or runtime import dependency on the vendored package. |
| `tests/plugins/test_scroll_stage0_monty.py` | Hermes-specific Stage 0 | Hermes project license | Tests the locked Monty protocol and containment boundary independently. |
| `tests/plugins/test_scroll_context_engine.py` | QwenPaw `scroll-research` `3db60c5975187fc7c549e16573567a7cd21fd51f`, `tests/unit/agents/context/test_memoryspace.py`, `test_repl_state.py` | Apache-2.0 | Clean-room behavioral ports only: SQL authorizer escape rejection, prepared values, preserved canonical history, and failure-not-empty output. No QwenPaw source or fixtures copied. |
| `evals/scroll/` | QwenPaw `scroll-research` `3db60c5975187fc7c549e16573567a7cd21fd51f`, `tests/unit/agents/context/test_scroll_manager.py` | Apache-2.0 | Clean-room deterministic adaptations of temporal/conflicting/exact/parallel/failed-retry/cache-resume/corruption behavior classes. Fixtures use only invented facts. |
| `evals/scroll/longmemeval.py` | Scroll `evaluation/scroll_eval/evals/longmemeval/ingest.py` and `evaluation/tests/test_longmemeval_ingest.py` at `313077708ea105cc79bf0a997338e14dae916f8c` | Apache-2.0 | Clean-room value-only adaptation: ISO dates and session-tagged turns become immutable Hermes snapshots, never a source SQLite database. |
| `evals/scroll/beam.py` | Scroll `evaluation/scroll_eval/evals/beam/ingest.py` and `evaluation/tests/test_beam_ingest.py` at `313077708ea105cc79bf0a997338e14dae916f8c` | Apache-2.0 | Clean-room value-only adaptation: marker stripping and inherited session dates become immutable Hermes snapshots, never a source SQLite database. |
| `evals/scroll/upstream_adapter.py` | Scroll `evaluation/scroll_eval/evals/{longmemeval,beam}/runner.py` at `313077708ea105cc79bf0a997338e14dae916f8c` | Apache-2.0 | Clean-room result-shape adapter. It accepts only `id`, `type`, `question`, and Hermes responses; source rubric/gold fields are excluded from judge input and model-visible data. |
| `scripts/run_scroll_upstream_evaluation_tests.sh`, `evidence/UPSTREAM-EVALUATION-DRIFT-LANE.md` | Scroll `evaluation/` and `evaluation/tests/` at `313077708ea105cc79bf0a997338e14dae916f8c` | Apache-2.0 | Does not copy or alter upstream code. It validates an independently checked-out pinned source tree, then runs its evaluation suite with a fixed test-only client value. |

Run the retained upstream drift lane with the Hermetic runner's per-file
executor. Its adjacent test-only import harness resolves `scroll_context` to
the vendored tree:

```bash
scripts/run_tests.sh plugins/context_engine/scroll/vendor/tests
```
