"""The future live runner must preserve pair symmetry and gold isolation."""

import copy
import threading
import time

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
        "provider": "openai-codex",
        "authentication_mode": "chatgpt-codex-oauth",
        "billing_mode": "chatgpt_subscription",
        "agent_model": "gpt-5.6-luna",
        "judge_model": "gpt-5.6-luna",
        "judge_source": "pinned-source",
        "temperature": 0,
        "seed": 1,
        "context_window_tokens": 100,
        "max_iterations": 2,
        "max_output_tokens": 25,
        "max_parallel_workers": 2,
        "input_token_budget": 100,
        "output_token_budget": 50,
        "cache_read_token_budget": 100,
        "source_revisions": {"source": "locked"},
        "licenses": {"source": "MIT"},
        "datasets": [{"name": "longmemeval", "revision": "locked", "item_ids": ["one", "two"]}],
        "arms": {"stock": "same-settings", "scroll": "same-settings"},
    }


def _usage(input_tokens=10, output_tokens=5, cache_read_tokens=0):
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "cache_read_tokens": cache_read_tokens}


def test_paired_runner_exposes_only_public_probe_fields_and_redacts_results():
    seen = []
    probes = [
        {"id": "one", "type": "fact", "question": "Which?", "answer": "hidden one", "rubric": "hidden"},
        {"id": "two", "type": "temporal", "question": "When?", "gold": "hidden two"},
    ]

    def execute(arm, probe):
        seen.append((arm, dict(probe)))
        return {"answer": f"{arm}:{probe['id']}", "usage": _usage()}

    report = run_paired_evaluation(_manifest(), probes, execute, lambda probe, answer: {"score": int(answer.endswith(probe["id"])), "usage": _usage()})

    assert all(set(probe) == {"id", "type", "question"} for _, probe in seen)
    assert report["billing_mode"] == "chatgpt_subscription"
    assert "total_cost_usd" not in report
    assert [(row["task_id"], row["arm"]) for row in report["rows"]] == [("one", "stock"), ("one", "scroll"), ("two", "stock"), ("two", "scroll")]
    assert all("answer" not in row and "gold" not in row and "rubric" not in row for row in report["rows"])


def test_paired_runner_runs_workers_in_parallel_and_preserves_row_order():
    probes = [{"id": "one", "type": "fact", "question": "Which?"}, {"id": "two", "type": "fact", "question": "What?"}]
    lock = threading.Lock()
    active = 0
    peak = 0

    def execute(arm, probe):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return {"answer": f"{arm}:{probe['id']}", "usage": _usage()}

    report = run_paired_evaluation(_manifest(), probes, execute, lambda *_: {"score": 1, "usage": _usage()})

    assert peak == 2
    assert [(row["task_id"], row["arm"]) for row in report["rows"]] == [("one", "stock"), ("one", "scroll"), ("two", "stock"), ("two", "scroll")]


def test_paired_runner_fails_closed_for_incomplete_pairs_or_budget_overruns():
    manifest = _manifest()
    probes = [{"id": "one", "type": "fact", "question": "Which?"}, {"id": "two", "type": "fact", "question": "What?"}]

    with pytest.raises(PairedRunError, match="complete ordered"):
        run_paired_evaluation(manifest, list(reversed(probes)), lambda *_: {}, lambda *_: {})
    over_budget = copy.deepcopy(manifest)
    with pytest.raises(PairedRunError, match="input_token_budget"):
        run_paired_evaluation(over_budget, probes, lambda *_: {"answer": "x", "usage": _usage(input_tokens=101)}, lambda *_: {"score": 1, "usage": _usage()})
    with pytest.raises(PairedRunError, match="numeric score"):
        run_paired_evaluation(_manifest(), probes, lambda *_: {"answer": "x", "usage": _usage()}, lambda *_: {"score": True})


def test_paired_runner_requires_complete_token_usage():
    probes = [{"id": "one", "type": "fact", "question": "Which?"}, {"id": "two", "type": "fact", "question": "What?"}]

    with pytest.raises(PairedRunError, match="cache_read_tokens"):
        run_paired_evaluation(_manifest(), probes, lambda *_: {"answer": "x", "usage": {"input_tokens": 1, "output_tokens": 1}}, lambda *_: {"score": 1, "usage": _usage()})
