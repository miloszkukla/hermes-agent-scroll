# Scroll security boundary

Monty is the only interpreter boundary for `scroll_repl`. Hermes approvals
govern host effects elsewhere; they do not weaken or replace the sandbox.
There is no CPython, terminal, WebSocket, or remote-interpreter fallback.

The only host callbacks are bounded `search`, `expand`, SELECT/CTE
`sql_query`, `stats`, opaque session/task identifiers, and date arithmetic.
They operate over an immutable, host-redacted snapshot, validate JSON-safe
inputs and outputs, and never pass a path, connection, environment value,
credential, raw artifact, or host object into Monty. The SQL callback creates
a fixed in-memory projection, uses `query_only`, an authorizer, a progress
budget, prepared bindings, and row limits.

Do not add a callback with host effects without a separate security review,
current session authority/approval integration, containment tests, and an
updated Stage 0 decision. Treat recovered history as untrusted data. Cache or
evidence artifacts must retain only redacted canonical fields.

## Known limitations

Monty is experimental and supports a Python subset. Its resource limits and
worker supervision are containment controls, not proof that arbitrary Python
semantics match CPython. The Stage 0 suite is therefore a stop/go gate for the
specific bootstrap, callbacks, and dependency lock in this plugin. A failed or
mismatched gate makes Scroll unavailable; it is never grounds to enable an
unsafe compatibility fallback. The disposable evaluation host is defense in
depth, not the sandbox boundary.

The callback SQL projection is intentionally reconstructed in memory from an
immutable snapshot. It is not a direct view of `state.db`, has no filesystem
or connection handle, and may expose degraded references rather than raw
non-text artifacts. Recalled text, including model-authored headlines, can
contain hostile instructions and must be treated as data.

## Changing this boundary

Any change to the Monty version, worker, interpreter lock, bootstrap, callback
surface, cache serialization, or resource limit requires a security review,
fresh Stage 0 evidence, containment and redaction tests, SBOM/provenance
updates, and a new pre-evaluation decision. A host-effecting callback also
requires explicit current-session authority and approval integration; approvals
must not be used as a substitute for the sandbox. Report suspected boundary
escapes privately to the Hermes maintainers with a minimal reproduction and do
not publish secrets, caches, or raw histories.
