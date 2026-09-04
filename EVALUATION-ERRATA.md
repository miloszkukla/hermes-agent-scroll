# Evaluation advisory: model-access assumptions

Date: 2026-09-03

This advisory supplements `PLAN.md` at the pre-live-evaluation checkpoint.
It does not change the implementation scope, prescribe a particular model,
or require current implementation and deterministic tests to pause.

Before live evaluation, inspect the reused Hermes, Scroll, and QwenPaw tests,
benchmark configurations, prompts, and graders for provider/model assumptions.
Determine which evaluations are model-independent and which require particular
model access for meaningful results. An upstream default model alone does not
establish that a test requires that model. Distinguish product validation on a
chosen model from reproduction of an upstream model-specific result.

Document your reasoning, source evidence, and chosen model/judge requirements
in the evaluation plan or manifest. Model selection remains the executing
agent's technical responsibility; this advisory does not mandate a Qwen lane
or assume that OpenAI access is sufficient for every evaluation.

Request any necessary access from the user before running the affected live
evaluations, explaining the specific model/provider and why it is needed.
Follow the existing credential, authorization, cost, and review boundaries in
`PLAN.md`; do not put secrets in this file, reports, or task messages.

Do not silently substitute models where doing so would invalidate the intended
comparison. If required access is unavailable, report the limitation and ask
for a decision on the affected evaluation rather than silently dropping it or
claiming equivalent evidence. Continue unaffected implementation and
deterministic tests.
