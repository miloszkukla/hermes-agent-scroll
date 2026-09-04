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
`c17b49e79c31632802433800eb46d4b17463449c`.

| Material | SHA-256 |
| --- | --- |
| Complete candidate diff from base (`git diff --binary base..candidate`) | `968458b539ed4067756365b3c4289d972f3595aed390f399c546519c89a73451` |
| Memory live manifest | `2946a1c850768e9095e0031aa5f3c12939acd96343c5304a32eb63100d8da310` |
| Coding live manifest | `78fabb4ed5dfbc1d463d7970385a1cf10e5f854a2cd4acc719334e70165c27b7` |
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
The disposition is recorded in [FRESH-LIVE-EXECUTOR-REVIEW-2026-09-04.md](FRESH-LIVE-EXECUTOR-REVIEW-2026-09-04.md), whose transport amendment records the explicit Chat Completions fix in this candidate.

The task owner authorized the two OpenRouter-backed live lanes and delivery
commits/pushes. The checkpoint precedes all live-model requests.
