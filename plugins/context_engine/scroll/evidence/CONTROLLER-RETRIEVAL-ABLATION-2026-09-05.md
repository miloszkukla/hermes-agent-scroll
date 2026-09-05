# Scroll controller-retrieval ablation — 2026-09-05

## Scope

This exploratory ten-item arm reuses the current frozen stock and advisory
Scroll results. Only the controller-guided Scroll answers and their pinned
judgments were newly generated. It is not an acceptance replacement.

The controller derives a query from the public question only: it lowercases,
deduplicates, removes common stopwords and short tokens, takes the first eight
remaining terms, then OR-joins them. It calls `ms.search(query, k=3)` and
appends the resulting bounded snippets as an explicitly untrusted data block
to the original user question. It has no access to gold answers, rubrics, or
the source conversation outside Scroll's read-only API. The answer model still
receives `scroll_repl` and may use it independently.

`ms.expand()` was deliberately not used by this controller: whole expanded
rows exceed Scroll's bounded cross-sandbox value size before the controller
can trim them. The runner's no-provider preflight caught that contract failure
before the live arm, then bound the final mechanism as `search_snippets_v1`.

| Item | SHA-256 / value |
| --- | --- |
| Experiment manifest | `548f52360f159b85e522a4cd1d8d84260e01696b3d4a6d141981cdd9dacdfd3f` |
| Experiment runner | `f037e1782be0caf309901fe70d57ff84408cb47ece2de295c45a8952c89f9d6a` |
| Controller report | `748b72a166229dccc37664a1e24fb122916323a777e65b5eb5ad858488fc74df` |
| Bound baseline manifest | `e09e421dc17858b713d6f9b5102118e5c64f4fa33726046b5e87743abfbd8d8f` |
| Bound baseline report | `14dd0adeec4612a7cd89533a2986a9416de3580ff114b42a31e4405b93b67f33` |

## Results

| Arm on the same ten items | Score total | Scroll retrieval |
| --- | ---: | --- |
| Stock baseline | `6.8333/10` | n/a |
| Advisory Scroll baseline | `5.2500/10` | 0 model calls on this subset |
| Static-policy Scroll | `5.2500/10` | 30 model calls on all 10 items |
| Controller-retrieval Scroll | `6.3333/10` | 10 controller searches; 4 model calls on 1 item |

Controller retrieval improves `1.0833` points over either previous Scroll arm
on this subset, but remains `0.5000` below stock. The improvement is concentrated
in LongMemEval multi-session recall (`+1.0` versus advisory Scroll) and BEAM
contradiction resolution (`+0.25`), partly offset by BEAM information extraction
(`-0.1667`). It neither improves the LongMemEval temporal item nor the BEAM
abstention and temporal items.

## Interpretation

The forced-use result and this controller arm jointly indicate that mere tool
adoption is not the whole bottleneck: forcing model-chosen searches did not
help, while a deterministic question-derived retrieval block recovered some
score. This is evidence that query/retrieval control may matter, not a general
performance claim. The sample is only ten cases, the controller changes the
answer input, and bounded snippets are weaker than a verified multi-step
search-and-expand controller. A larger preregistered controller arm would be
needed before drawing a product or paper conclusion.
