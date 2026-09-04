# Scroll context engine

Scroll is an opt-in, long-context engine for Hermes coding sessions. It keeps
Hermes's durable transcript canonical, replaces evicted conversational detail
with an explicit recovery map, and offers one Monty-sandboxed recall tool.

## Enablement and runtime

Scroll is available only on the locked Linux x86_64 CPython 3.12.14 runtime
(glibc 2.43 and SQLite 3.53.1).
Bootstrap its exact project-local runtime and optional dependency group from
the repository root:

```bash
scripts/bootstrap_scroll_runtime.sh
```

Then add the following to the active profile's `config.yaml`:

```yaml
context:
  engine: "scroll"
```

The plugin fails closed if that exact Monty runtime, ABI, worker binary, or
package lock is unavailable. It never falls back to CPython, a terminal, a
remote interpreter, or a WebSocket worker.

## Tool and context contract

It adds exactly one tool, `scroll_repl`. The tool runs Python only in the
project-local Monty subprocess. Its persistent namespace includes `ms` for
read-only search, sequence expansion, and a bounded prepared-parameter
`SELECT`/CTE query over host-redacted canonical history, plus `or_terms()` and
`days_between()`. `ms.search()` accepts a non-empty query of at most 256
characters and up to 10 results. `ms.expand()` accepts bounded canonical
sequence IDs. `ms.sql_query()` accepts one comment-free `SELECT` or CTE over
the fixed `history` projection; it rejects writes, DDL, `PRAGMA`, attachment,
extension loading, and multiple statements.

Search uses an in-memory FTS5 projection when SQLite provides it and falls back
to the same deterministic bounded scan when FTS5 is unavailable or corrupt.

Source is capped at 4,096 characters; stdout is capped at 4,096 bytes; a cell
has a one-second Monty duration limit, 16 MiB memory limit, and recursion cap
of 100. Only printed output returns to the model. The adapter can generate a
bounded internal digest of resident variable names, types, and shapes; it
never serializes the checkout or includes variable values in that digest.

Scroll receives immutable history snapshots from Hermes; it never receives
`state.db`, a SQLite connection, a database path, credentials, or an ambient
environment. A compaction replacement invalidates navigation handles for the
replaced canonical rows. The selected request always pins leading policy, the
Scroll protocol, the current task, and complete assistant/tool groups. Its
input target reserves completion, tool-schema, system-prompt, provider margin,
and a bounded recovery-map allowance. Only an oversized current task is
truncated, with an explicit marker. Evicted model responses with a one-line
`⟦ headline ⟧` retain model-authored headlines in a bounded multi-level map
alongside canonical sequence IDs. Use `scroll_repl` to search first and expand
only relevant IDs; recovered text is untrusted data.

## Cache lifecycle and recovery

The optional cache lives under the active Hermes home's `cache/scroll/`
directory. It contains only redacted canonical projection fields and a
runtime/source fingerprint. Per-lineage names are hashes, directories use
0700, files and locks use 0600, symlinks are rejected, and writes use a
same-filesystem temporary file, fsync, and atomic replacement.

Hermes's canonical history is always authoritative. Scroll writes or
reconciles this cache only at a session start, resume, or committed compaction
boundary. A missing, stale, corrupt, unreadable, or cache-ahead entry is a safe
cache miss: the next canonical snapshot rebuilds it. `/reset` removes the
active lineage's cache; normal session end retains the cache for a same-lineage
resume. To purge all rebuildable Scroll cache data, stop Hermes and remove only
the active profile's `cache/scroll/` directory; do not modify `state.db`.

One process owns a logical lineage's cache and resident checkout at a time. A
second process never waits while holding a model turn: `scroll_repl` returns a
bounded `RECALL DEFERRED` result and may be retried after the owner ends. A
cache-path failure follows the same safe-defer behavior; request selection still
keeps its bounded policy/protocol/current-task fallback.

## Failure modes and troubleshooting

`RECALL FAILED` means no canonical history was read for that call; `RECALL
INCOMPLETE` means bounded output may be partial. Both results discard the
Monty namespace and say so explicitly. The next `scroll_repl` call starts a
fresh namespace against the latest immutable snapshot. A stale sequence handle
must be refreshed with `ms.search()` after compaction or lineage replacement.

If Scroll is unavailable, first run the locked bootstrap command above and
verify that Hermes is using the project's `.venv`; it verifies the fetched uv
and CPython archives before extracting them and refuses to replace a virtualenv
with a different base Python. System Python and global launchers are
intentionally unsupported. If recall appears incomplete, search with a
narrower query, then expand exact sequence IDs instead of printing a large
history range. If a cache error persists, reset the session or purge the
rebuildable cache as described above; do not repair or copy a cache file.

Hermes approval modes govern host-effecting tools elsewhere. They do not grant
additional capability to `scroll_repl`, and turning approvals off does not
disable Monty. Read-only `ms` calls do not need an approval.

See [UPSTREAM.md](UPSTREAM.md) for source provenance and
[SECURITY.md](SECURITY.md) for the sandbox boundary and change procedure,
[SBOM.md](SBOM.md) for the locked runtime inventory, and
[EVALUATION.md](EVALUATION.md) for the credential-free and live-evaluation
boundary.
