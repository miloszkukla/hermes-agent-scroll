# Scroll pre-commit review bundle

## Status

**Immutable pre-evaluation checkpoint.** The candidate and two credential-free
live manifests below were independently reviewed and cleared for the recorded
two live lanes. No API credential, raw history, answer, trace, corpus, cache,
or virtual environment is included.

## Snapshot identity

Captured on 2026-09-04 against Hermes base
`29112bef099274229cadff79cdff7bf7b99c4b77` (`v2026.8.31`) on branch
`codex/scroll-plugin`, candidate
`f86f3bb2f3f3a6de517b82382eb17e30277eb763`.

| Material | SHA-256 |
| --- | --- |
| Complete candidate diff from base (`git diff --binary base..candidate`) | `f81db4bd418cfdedda49393bca91414cc1e95be88d40ab89e2513c1f09a8795b` |
| Memory live manifest | `573680481d35fde73d48a89e0b4797425107f48e8372d8b4422fc3d8d7b58566` |
| Coding live manifest | `ac484670fc0f2a5c8da77fee2caa9f963563cc377fbbbd7efc31fdcf7671bb73` |
| Plan | `7031dc9351254dd2846f1471f958b32b9b1ecbca112352d3ca047260a5cd8210` |
| Credential-free manifest | `b8356f7971b9a0c16d33f564c84e39d194fc55d2f6308de4f55a5448ab9f536e` |
| Stage 0 report | `295aacf7cbadcd197d5b82bd70b6a4d5edb27049099735302acb9541413dc7d3` |

The manifests are reviewed delivery files. They pin the same stock/Scroll
settings, the exact implementation candidate, prompts, source revisions,
dataset IDs, budgets, pricing, and cost ceilings; validation rejects
credential-shaped fields. They remain outside the implementation-provenance
diff by design, so this evidence-only checkpoint can follow the candidate
without changing the code under test.

## Reviewer starting points

- [Stage 0 containment report](STAGE0-STOP-GO.md) and its checksum.
- [Pre-evaluation readiness](PRE-EVALUATION-READINESS.md) for test evidence
  and remaining blockers.
- [Paper scope review](PAPER-SCOPE-REVIEW.md) for the rendered PDF and TeX
  crosswalk and intentional non-equivalence.
- [`README.md`](../README.md), [`SECURITY.md`](../SECURITY.md),
  [`EVALUATION.md`](../EVALUATION.md), [`UPSTREAM.md`](../UPSTREAM.md), and
  [`PROVENANCE.md`](../PROVENANCE.md) for public contract, boundaries, and
  source handling.

## Required review outcome

The independent reviewer `/root/final_fresh_review` inspected the complete
candidate and both manifests. It found no actionable P0/P1/P2 after verifying
the host `_compress_context` lifecycle, valid OpenAI tool-call replay shape,
100K-token histories, paired bootstrap/p95 accounting, dirty/untracked source
rejection, LongMemEval corpus hashing, and source-CWD `scroll_eval` imports.
The disposition is recorded in [FRESH-LIVE-EXECUTOR-REVIEW-2026-09-04.md](FRESH-LIVE-EXECUTOR-REVIEW-2026-09-04.md).

The task owner authorized the two OpenRouter-backed live lanes and delivery
commits/pushes. The checkpoint precedes all live-model requests.
