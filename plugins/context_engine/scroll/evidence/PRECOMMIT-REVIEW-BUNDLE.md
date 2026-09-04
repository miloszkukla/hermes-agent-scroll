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
`6fc652d37c78d0c598cb11b11de12bfe2359ea3b`.

| Material | SHA-256 |
| --- | --- |
| Complete candidate diff from base (`git diff --binary base..candidate`) | `58161d14b166fa8abff1952d5d3d26f682d44f9474f4cec2daf8d63a46c65607` |
| Memory live manifest | `ebc2ec7fc6cb3c139a5196e3aa83e72132e926bb553b2fed61cfcf0620c8f113` |
| Coding live manifest | `bde905f095791bfcd412641f1e4d495acd860a958b8a4e948cea8adb6c38de2b` |
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
The disposition is recorded in [FRESH-LIVE-EXECUTOR-REVIEW-2026-09-04.md](FRESH-LIVE-EXECUTOR-REVIEW-2026-09-04.md), whose amendments record the explicit Chat Completions, terminal-isolation, and auxiliary-output-cap fixes in this candidate.

The task owner authorized the two OpenRouter-backed live lanes and delivery
commits/pushes. The checkpoint precedes all live-model requests.
