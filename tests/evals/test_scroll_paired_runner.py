"""The future live runner must preserve pair symmetry and gold isolation."""

import copy

import pytest

from evals.scroll.paired_runner import PairedRunError, run_paired_evaluation


def _manifest():
    return {
        "schema_version": 1,
        "live_model": True,
        "implementation_commit": "a" * 40,
        "plan_sha256": "b" * 64,
        "credential_free_manifest_sha256": "c" * 64,
        "agent_prompt_sha256": "d" * 64,
        "provider": "approved-provider",
        "authentication_mode": "interactive-approved",
        "agent_model": "approved-agent",
        "judge_model": "approved-judge",
        "judge_source": "pinned-source",
        "service_tier": "flex",
        "temperature": 0,
        "seed": 1,
        "context_window_tokens": 100,
        "max_iterations": 2,
        "max_output_tokens": 25,
        "input_token_budget": 100,
        "output_token_budget": 50,
        "cache_read_token_budget": 100,
        "input_price_per_token": 0.000001,
        "output_price_per_token": 0.000002,
        "cache_read_price_per_token": 0.0000001,
        "cost_ceiling_usd": 1.0,
        "source_revisions": {"source": "locked"},
        "licenses": {"source": "MIT"},
        "datasets": [{"name": "longmemeval", "revision": "locked", "item_ids": ["one", "two"]}],
        "arms": {"stock": "same-settings", "scroll": "same-settings"},
    }


def test_paired_runner_exposes_only_public_probe_fields_and_redacts_results():
    seen = []
    probes = [
        {"id": "one", "type": "fact", "question": "Which?", "answer": "hidden one", "rubric": "hidden"},
        {"id": "two", "type": "temporal", "question": "When?", "gold": "hidden two"},
    ]

    def execute(arm, probe):
        seen.append((arm, dict(probe)))
        return {"answer": f"{arm}:{probe['id']}", "usage": {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.1}}

    report = run_paired_evaluation(_manifest(), probes, execute, lambda probe, answer: {"score": int(answer.endswith(probe["id"]))})

    assert [arm for arm, _ in seen] == ["stock", "scroll", "stock", "scroll"]
    assert all(set(probe) == {"id", "type", "question"} for _, probe in seen)
    assert report["total_cost_usd"] == pytest.approx(0.4)
    assert [(row["task_id"], row["arm"]) for row in report["rows"]] == [("one", "stock"), ("one", "scroll"), ("two", "stock"), ("two", "scroll")]
    assert all("answer" not in row and "gold" not in row and "rubric" not in row for row in report["rows"])


def test_paired_runner_counts_judge_usage_against_the_shared_cost_ceiling():
    probes = [{"id": "one", "type": "fact", "question": "Which?"}, {"id": "two", "type": "fact", "question": "What?"}]

    with pytest.raises(PairedRunError, match="cost_ceiling"):
        run_paired_evaluation(
            _manifest(), probes,
            lambda *_: {"answer": "x", "usage": {"cost_usd": 0.1}},
            lambda *_: {"score": 1, "usage": {"cost_usd": 0.2}},
        )


def test_paired_runner_fails_closed_for_incomplete_pairs_or_budget_overruns():
    manifest = _manifest()
    probes = [{"id": "one", "type": "fact", "question": "Which?"}, {"id": "two", "type": "fact", "question": "What?"}]

    with pytest.raises(PairedRunError, match="complete ordered"):
        run_paired_evaluation(manifest, list(reversed(probes)), lambda *_: {}, lambda *_: {})
    over_budget = copy.deepcopy(manifest)
    over_budget["cost_ceiling_usd"] = 0.1
    with pytest.raises(PairedRunError, match="cost_ceiling"):
        run_paired_evaluation(over_budget, probes, lambda *_: {"answer": "x", "usage": {"cost_usd": 0.1}}, lambda *_: {"score": 1})
    with pytest.raises(PairedRunError, match="numeric score"):
        run_paired_evaluation(_manifest(), probes, lambda *_: {"answer": "x", "usage": {}}, lambda *_: {"score": True})
