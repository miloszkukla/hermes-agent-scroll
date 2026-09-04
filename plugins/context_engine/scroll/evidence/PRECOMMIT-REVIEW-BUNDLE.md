# Scroll pre-commit review bundle

## Status

**Superseded pre-candidate snapshot, not a pre-evaluation GO.** The hashes
below record the earlier implementation-only review snapshot. They predate the
reviewed live executors and are retained for traceability only; the candidate
commit and a new complete-diff review bundle are required before `GO`.

## Snapshot identity

Captured on 2026-09-04 against Hermes base
`29112bef099274229cadff79cdff7bf7b99c4b77` (`v2026.8.31`) on branch
`codex/scroll-plugin`.

| Material | SHA-256 |
| --- | --- |
| Complete tracked diff from `HEAD` (`git diff --binary HEAD`) | `5c866b919690ff71060812d05dcca820199ef345bf73bb0cecf8819bc872edf5` |
| Staged diff (`git diff --cached --binary`) | `c64528e74c04f6bd37493e875914bb1cd9118cb08a0b4f826999eec1cbe5ecf6` |
| Unstaged tracked diff (`git diff --binary`) | `d1738f8139acf80ccf4b3c9e7302bbbfa217a43f5a3a6be1e27e9dbfbc79827b` |
| Untracked delivery files | `ac8efd04a80a2eb6c9dc9dc083dae6c2f84ba42c2ba14cc519ec1197ba6fc6e0` |
| Plan | `7031dc9351254dd2846f1471f958b32b9b1ecbca112352d3ca047260a5cd8210` |
| Credential-free manifest | `b8356f7971b9a0c16d33f564c84e39d194fc55d2f6308de4f55a5448ab9f536e` |
| Stage 0 report | `295aacf7cbadcd197d5b82bd70b6a4d5edb27049099735302acb9541413dc7d3` |

The untracked-delivery hash is the SHA-256 of the `sha256sum` output for paths
from `git ls-files --others --exclude-standard`, sorted by path and excluding
this self-describing file. It covers the Scroll plugin, vendored source,
deterministic evaluation adapter, evidence, and tests without mutating the
index.

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

The reviewer must inspect the complete integrated diff and explicitly cover
canonical-history lifecycle, compaction and suffix merging, Monty/callback
containment, failure recovery, test assertions, secret handling, and paired
evaluation fairness. Record reviewer identity, findings and dispositions, and
a fresh test/artifact location in the readiness record. Resolve every P0/P1
finding before GO.

No provider authentication, live-model benchmark, commit, or push is
authorized by this bundle.
