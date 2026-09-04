"""The upstream judge adapter must keep gold fields outside the agent path."""

import json

import pytest

from evals.scroll.upstream_adapter import answers_for_upstream_judge, model_probes, normalize_upstream_result


def test_upstream_adapter_strips_gold_probe_fields_and_groups_in_judge_order():
    probes = [
        {"id": "p1", "type": "temporal", "question": "When?", "rubric": "hidden gold"},
        {"id": "p2", "type": "temporal", "question": "How long?", "answer": "also hidden"},
        {"id": "p3", "type": "abstention", "question": "Unknown?", "ideal_answer": "hidden"},
    ]

    model_input = model_probes(probes)
    answers = answers_for_upstream_judge(probes, {"p1": "Monday", "p2": "Two days", "p3": "Unknown"})

    assert model_input == [
        {"id": "p1", "type": "temporal", "question": "When?"},
        {"id": "p2", "type": "temporal", "question": "How long?"},
        {"id": "p3", "type": "abstention", "question": "Unknown?"},
    ]
    assert answers == {
        "temporal": [
            {"id": "p1", "question": "When?", "llm_response": "Monday"},
            {"id": "p2", "question": "How long?", "llm_response": "Two days"},
        ],
        "abstention": [{"id": "p3", "question": "Unknown?", "llm_response": "Unknown"}],
    }
    assert "hidden" not in json.dumps({"answers": answers, "model_input": model_input})


def test_upstream_adapter_rejects_incomplete_answers_and_normalizes_judge_scores():
    probes = [{"id": "p1", "type": "fact", "question": "Which?"}]
    with pytest.raises(ValueError, match="match unique probe ids"):
        answers_for_upstream_judge(probes, {"other": "answer"})

    answers = answers_for_upstream_judge(probes, {"p1": "answer"})
    row = normalize_upstream_result("scroll", "beam", "100K-1", answers, {
        "overall_reward": 0.75, "per_type": {"fact": {"mean": 0.75}},
    })

    assert row == {
        "schema_version": 1,
        "arm": "scroll",
        "benchmark": "beam",
        "task_id": "100K-1",
        "answer_count": 1,
        "overall_reward": 0.75,
        "per_type": {"fact": {"mean": 0.75}},
    }
