# Scroll oracle-retrieval diagnostic — 2026-09-05

## Scope

This is a deliberately non-production, non-paper diagnostic on the same ten
items used by the policy and controller-retrieval arms. It reuses the frozen
stock, advisory-Scroll, policy-Scroll, and question-derived-controller reports;
only the oracle-arm answers and judgments are fresh.

For each item, the controller privately extracts only answer-bearing gold
fields from this ordered set: `answer`, `ideal_answer`, `ideal_response`.
It tokenizes those values, backfills with public-question terms, forms a
bounded OR query, and calls `ms.search(query, k=3)`. The model receives only
the returned snippets in the same untrusted controller-retrieval block as the
previous controller arm. It never receives the gold field, rubric, or oracle
query. One-use private job files hold the hint only until the worker starts;
durable rows contain its SHA-256, never its value.

This measures a gold-conditioned lexical-retrieval ceiling, not an achievable
product path. It must not be used for acceptance, performance, or paper claims.

| Item | SHA-256 / value |
| --- | --- |
| Experiment manifest | `61c48ac6f74730d406a8a5f9f33459d05d686cc8216d347ac9a59690d485c97d` |
| Experiment runner | `727579fa5ca35fdb17c983a82b64b31b1b5d87ee9a224f29b2cfd259249d6071` |
| Oracle report | `76142373cf7b94e3f14aa1bd4c452211c289c7cf46c11d401158e64e162430b9` |
| Frozen memory report | `14dd0adeec4612a7cd89533a2986a9416de3580ff114b42a31e4405b93b67f33` |
| Policy report | `e4c6203e9ab9620d7e1446f1e7af0f5e93bf1711a4c08fbf6648b29c6b6c27b1` |
| Controller report | `748b72a166229dccc37664a1e24fb122916323a777e65b5eb5ad858488fc74df` |

## Results

| Arm on the same ten items | Score total | Scroll retrieval |
| --- | ---: | --- |
| Stock baseline | `6.8333/10` | n/a |
| Advisory Scroll baseline | `5.2500/10` | 0 model calls on this subset |
| Static-policy Scroll | `5.2500/10` | 30 model calls on all 10 items |
| Question-derived controller | `6.3333/10` | 10 controller searches; 4 model calls on 1 item |
| Gold-conditioned oracle | `7.0833/10` | 10 oracle searches; 2 model calls on 1 item |

Oracle retrieval is `+0.7500` over the question-derived controller and
`+0.2500` over stock on this diagnostic subset. The controller-to-oracle gain
comes from BEAM temporal reasoning (`0.0` to `1.0`), partly offset by BEAM
contradiction resolution (`0.5` to `0.25`). The oracle still scores zero on
LongMemEval temporal reasoning and BEAM abstention.

## Interpretation

The result establishes a narrow capability fact: when the retrieval query is
conditioned on the answer, bounded Scroll snippets can support a materially
better answer on at least one previously unrecovered case. It does not show
that Scroll should outperform stock, because the query has information no real
controller has. Together with the forced-policy and question-controller arms,
the likely remaining work is a realistic query planner/retrieval policy and
separate investigation of abstention and temporal-reasoning failures—not more
forced tool adoption tests.
