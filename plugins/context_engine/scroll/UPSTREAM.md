# Scroll upstream record

This plugin vendors `niceIrene/Scroll` at commit
`313077708ea105cc79bf0a997338e14dae916f8c`, licensed Apache-2.0, under
`vendor/scroll_context/`. The upstream project has no `NOTICE` file. Its
Apache-2.0 `LICENSE` and all package data (`core.md`, `index.md`) are retained.
The upstream package tests are retained under `vendor/tests/` without edits.

The local patch inventory is deliberately narrow:

- every absolute `scroll_context` import is package-relative so the vendored
  package cannot collide with an installed upstream package;
- a test-only `vendor/tests/conftest.py` places the vendored package root on
  `sys.path` so the unmodified upstream tests retain their original
  `scroll_context` imports;
- the upstream CPython runtime remains preserved for upstream drift review but
  is never imported by the adapter; `sandbox.py` is the only runtime boundary;
- the Hermes adapter retains the upstream protocol/tool name while replacing
  its SQLite history attachment with immutable `CanonicalHistorySnapshot`
  callbacks. No upstream executor, database path, or host connection crosses
  into the sandbox.

Before updating: review upstream license/NOTICE changes, copy package data and
tests, convert absolute `scroll_context` imports to package-relative imports,
record every local patch here, rerun upstream drift tests and the Monty Stage 0
suite, then refresh the pinned commit above.
