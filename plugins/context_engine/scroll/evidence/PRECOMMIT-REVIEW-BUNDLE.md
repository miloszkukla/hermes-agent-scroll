# Scroll pre-commit review bundle

## Status

**GO for the frozen ChatGPT Codex OAuth candidate; the Flex-tier GO below is
historical.** The current candidate, credential-free manifests, and independent
review disposition are recorded in
[CHATGPT-OAUTH-PARALLEL-REVIEW-2026-09-04.md](CHATGPT-OAUTH-PARALLEL-REVIEW-2026-09-04.md).
The historical candidate and two credential-free live manifests below contain
no API credential, raw history, answer, trace, corpus, cache, or virtual
environment.

## Snapshot identity

Captured on 2026-09-04 against Hermes base
`29112bef099274229cadff79cdff7bf7b99c4b77` (`v2026.8.31`) on branch
`codex/scroll-plugin`, candidate
`10869fc0bb736bff89ce365d0d79f13831fd4d21`.

| Material | SHA-256 |
| --- | --- |
| Complete candidate diff from base (`git diff --binary base..candidate`) | `ea981844a803022fd481f6cbe6a1195056a3850bf54ba4b29e978bc87ad3b556` |
| Memory live manifest | `6b4c692d94ed5a0dfda5410c00b99fbbd39e3de7000332b9de89e27343b03ce4` |
| Coding live manifest | `48d88ebaa11cf64ea1996f562bf2fc03b197f5af54c4836dcebdc19bbe6d14a6` |
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

The independent reviewer `/root/final_fresh_review` cleared earlier candidates
for the host `_compress_context` lifecycle, valid OpenAI tool-call replay shape,
100K-token histories, paired bootstrap/p95 accounting, dirty/untracked source
rejection, LongMemEval corpus hashing, and source-CWD `scroll_eval` imports.
That disposition is recorded in [FRESH-LIVE-EXECUTOR-REVIEW-2026-09-04.md](FRESH-LIVE-EXECUTOR-REVIEW-2026-09-04.md), but it predates this Flex amendment. Its first two Flex reviews found omitted cache-read billing and then non-fail-closed auxiliary/worker accounting; the third found malformed judge usage defaulting to zero. The reviewed replacements culminate in `10869fc0bb736bff89ce365d0d79f13831fd4d21`. The independent reviewer completed the complete candidate-and-manifest review with a 35-test fresh focused suite and **GO**; no actionable P0/P1/P2 remains.

The task owner authorized the two OpenRouter-backed live lanes and delivery
commits/pushes. This renewed GO checkpoint precedes the authorized live-model
requests.
