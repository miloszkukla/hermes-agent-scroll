# Stage 0 Monty Stop/Go Report

## Decision

**GO.** The required Monty compatibility and containment spike passed on the
locked Linux runtime. This authorizes deterministic adapter work only; it does
not authorize a live-model evaluation.

## Hash-bound attestation

Executor: Codex automated execution

Signature: hash-bound execution attestation; no user credential, signing key,
or model credential was used.

The companion `STAGE0-STOP-GO.sha256` file binds this report's contents. Any
change to its inputs or test harness invalidates this decision and requires a
fresh run.

## Baseline and inputs

| Item | Value |
| --- | --- |
| Hermes release tag object | `6e8f8418e6378eb2617e4de074e13dedd091b8af` |
| Hermes release commit | `29112bef099274229cadff79cdff7bf7b99c4b77` |
| Scroll source commit | `313077708ea105cc79bf0a997338e14dae916f8c` |
| Plan SHA-256 | `7031dc9351254dd2846f1471f958b32b9b1ecbca112352d3ca047260a5cd8210` |
| `pyproject.toml` SHA-256 | `b7d1e7aaee69f2def3d9a7e3d2fa3fe64ca36cc535d26382b0745daa9f22a07f` |
| `uv.lock` SHA-256 | `2b9d63f9ceb4c5a2a2aeb42ee843c1c4ebd48deccb6633f50a9519f4464c381d` |
| Stage 0 harness SHA-256 | `35b84c753e2c83ed04bb488eed12ef33b344b79b94cf7c888d3980439c8fa561` |

The old checkout and its staged plan/bootstrap state remain recoverable at
local ref `codex/scroll-preflight-recovery` (`a46fc8e234a5c99ccab358808becbfb651b26f6c`).

## Locked runtime

| Artifact | Verified value |
| --- | --- |
| uv | `0.12.9`, archive SHA-256 `ec7a99cd05e0cd7f80243f135ce1361c76835cb0ee60055d14d20eba8eba1460` |
| CPython | `3.12.14+20260901`, archive SHA-256 `72748da13197c1fb161e3afeef20a6a385ff24f2165e6e2758e47008e7faba4c` |
| ABI | `cpython-312` |
| glibc | Ubuntu glibc `2.43` |
| SQLite | `3.53.1` |
| `pydantic-monty`, client, runtime | `0.0.21` |
| Monty worker | SHA-256 `bc4767743e5fb9fa360fbee21ded25e2642d8ad89a5c4f81b02a67d66c93a385` |
| Worker protocol | local subprocess protocol, supported range `1..1` |

The uv and CPython archives were downloaded from their canonical locked
release URLs and digest-verified before the project-local `.venv` was built.
System CPython 3.14 was not changed.

## Command and result

```console
scripts/run_tests.sh tests/plugins/test_scroll_stage0_monty.py
```

Result: **18 passed**.

The harness proves exact runtime identity and package-record fail-closed
verification; persistent variables, functions, classes, comprehensions,
the deployed `sandbox.BOOTSTRAP` and `MontyScrollRepl` callback façade,
`or_terms`, `days_between`, reserved-name rebinding,
bounded JSON conversion, bounded working-memory digests without checkout
serialization, expression-result suppression, stdout limits, in-sandbox time,
memory, and recursion limits, and parent-watchdog worker replacement.

Containment assertions prove a dropped host environment sentinel, denied host
filesystem access, denied `os.environ`, unavailable network/process modules,
blocked ambient-object introspection, and rejection of raw host-object
serialization. No mount, OS callback, WebSocket worker, CPython executor, or
fallback runtime was used.
