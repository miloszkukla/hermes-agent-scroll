# Paper scope review

## Inputs reviewed

- The rendered arXiv v1 PDF, [2608.21690](https://arxiv.org/pdf/2608.21690),
  has SHA-256
  `70ee5193dddfed81cb83e154083dbcafaf5fa6067bd125f12a150dcbc8d229d4`.
  Its Figure 1 and Table 1 were rendered and visually inspected.
- The matching arXiv TeX source,
  [e-print 2608.21690](https://arxiv.org/e-print/2608.21690), was read from
  `main.tex` (`dcab4c54c7d93a75fb0b4386e3ddab091b4fdb6efde8f0381a70280d0d66e532`),
  `sections/method.tex`
  (`fac6d0d4487a1e93e8f819b9d2a157389822726112812ae4af8a426b9b7aac67`),
  `sections/setup.tex`
  (`55fee56182bd8f9f299c9797cce2a45e2a456e468b5f6001ce1e67572a2c8c93`), and
  `sections/results.tex`
  (`7cba2f922e855bd23cbfb053df6dab5a5522f83f7e3935b11b1c9b484fc8d232`).

## Scope crosswalk

| Paper concept | Hermes Scroll decision | Disposition |
| --- | --- | --- |
| Append-only Event Log, persistent namespace, bounded printed working view, and recoverable eviction index | Canonical immutable Hermes snapshot, one persistent Monty namespace, printed-only output, and a bounded headline/sequence recovery map | Deliberately aligned at the behavioral level. Hermes history remains canonical. |
| `ms.search` and `ms.expand` identify and materialize stable Event Log addresses | Read-only callbacks search and expand host-redacted, generation-scoped canonical rows | Deliberately aligned, with stale handles rejected after a compaction-generation boundary. |
| General Python plus permitted database, filesystem, and tool interfaces in the paper's session environment | One `scroll_repl` tool executes only in Monty. The callback surface is read-only search, expand, bounded SELECT/CTE query, stats, and date arithmetic; no filesystem, network, process, host tool, path, connection, or credential crosses the boundary | Intentional security restriction, not a missing capability. |
| QwenPaw exposes separate `repl_exec` and `recall_history_python` actions and evaluates LOCA | Hermes exposes exactly one `scroll_repl` schema and excludes `repl_exec`/LOCA | Intentional integration boundary. The paper's broader agent environment is not an implementation contract. |
| Published LongMemEval, BEAM, and LOCA scores on QwenPaw/backbone-specific settings | Eight deterministic synthetic cases and future paired Hermes stock/plugin lanes under a reviewed manifest | Published numbers are context only. They are neither reproduced nor used as acceptance baselines. |

## Review conclusion

The paper supports the plan's conceptual terms and explains why a persistent,
programmatic recall environment can be useful. It does not authorize a raw
CPython kernel, a second host tool, the paper's QwenPaw capability surface, or
a performance/equivalence claim. A fresh-context reviewer must treat the
Monty Stage 0 report and the Hermes-specific deterministic evidence as the
relevant implementation proof, not this comparison.
