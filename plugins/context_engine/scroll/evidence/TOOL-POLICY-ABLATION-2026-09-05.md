# Scroll tool-policy ablation — 2026-09-05

## Scope

This is exploratory evidence, not an acceptance replacement. It reuses the
current 48-item stock and advisory-Scroll report only as a frozen baseline, then
runs a static policy-only Scroll arm on the deterministic ten-item subset pinned
by `scroll-tool-policy-10-20260905-manifest.json`. The implementation, model,
judge, source revisions, budgets, and worker count remain bound to the current
memory lane. No old agent answer is reused by the policy arm.

| Item | SHA-256 / value |
| --- | --- |
| Experiment manifest | `44f2a4651adef884388130dae80ccfbcd52d0249633189acee2929eb5a2caeec` |
| Experiment runner | `5b44891479d04bf0f8792805e257c4199d1fd72a5ec65ba6ebbc02c72e3e6974` |
| Policy report | `e4c6203e9ab9620d7e1446f1e7af0f5e93bf1711a4c08fbf6648b29c6b6c27b1` |
| Bound baseline manifest | `e09e421dc17858b713d6f9b5102118e5c64f4fa33726046b5e87743abfbd8d8f` |
| Bound baseline report | `14dd0adeec4612a7cd89533a2986a9416de3580ff114b42a31e4405b93b67f33` |

The runner supplies a stable system policy requiring `scroll_repl` before every
answer: search with question terms, expand relevant sequence IDs, inspect the
result, then answer. It is a policy ablation, not API-level forced tool choice.

## Results

| Arm on the same ten items | Score total | Scroll use |
| --- | ---: | ---: |
| Stock baseline | `6.8333/10` | n/a |
| Advisory Scroll baseline | `5.2500/10` | 0 calls on 0/10 items |
| Policy Scroll | `5.2500/10` | 30 calls on 10/10 items |

Every policy answer digest differs from its advisory-Scroll counterpart, so the
unchanged score is not a replay artifact. Policy Scroll is unchanged from the
advisory baseline and remains `1.5833` points below stock on this subset.

## Interpretation

The original regression cannot be explained solely by Luna declining to invoke
the tool: the policy causes universal adoption on this subset without a score
gain. The sample is too small for a performance claim or formal significance
test. The next useful experiment, if warranted, is a controller-retrieval arm
that separates model query/tool reasoning from Scroll search and expansion.
