"""Pure adapter from Hermes probe answers to pinned Scroll judge input."""

from __future__ import annotations

from typing import Any


_BENCHMARKS = {"beam", "longmemeval"}


def model_probes(probes: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Project source probes to the only fields that may enter Hermes context."""
    result = []
    for probe in probes:
        if not isinstance(probe, dict):
            raise ValueError("every probe must be an object")
        identifier, question_type, question = (probe.get(key) for key in ("id", "type", "question"))
        if not all(isinstance(value, str) and value for value in (identifier, question_type, question)):
            raise ValueError("every probe requires non-empty id, type, and question strings")
        result.append({"id": identifier, "type": question_type, "question": question})
    if len({probe["id"] for probe in result}) != len(result):
        raise ValueError("probe ids must be unique")
    return result


def answers_for_upstream_judge(probes: list[dict[str, Any]], responses: dict[str, str]) -> dict[str, list[dict[str, str]]]:
    """Group Hermes answers in the upstream judge shape without exposing gold fields."""
    if not isinstance(responses, dict):
        raise ValueError("responses must be a mapping")
    model_input = model_probes(probes)
    expected_ids = [probe["id"] for probe in model_input]
    if set(responses) != set(expected_ids) or len(expected_ids) != len(set(expected_ids)):
        raise ValueError("responses must match unique probe ids exactly")
    if not all(isinstance(response, str) for response in responses.values()):
        raise ValueError("responses must be strings")
    grouped: dict[str, list[dict[str, str]]] = {}
    for probe in model_input:
        grouped.setdefault(probe["type"], []).append({"id": probe["id"], "question": probe["question"], "llm_response": responses[probe["id"]]})
    return grouped


def normalize_upstream_result(arm: str, benchmark: str, task_id: str, answers: dict[str, list[dict[str, str]]], scores: dict[str, Any]) -> dict[str, Any]:
    """Return a stable paired-run row after an upstream judge has scored answers."""
    if arm not in {"stock", "scroll"}:
        raise ValueError("arm must be stock or scroll")
    if benchmark not in _BENCHMARKS or not isinstance(task_id, str) or not task_id:
        raise ValueError("benchmark and task_id are required")
    if not isinstance(scores.get("overall_reward"), (int, float)):
        raise ValueError("scores must include numeric overall_reward")
    answer_count = sum(len(rows) for rows in answers.values())
    if not answer_count:
        raise ValueError("answers must not be empty")
    return {
        "schema_version": 1,
        "arm": arm,
        "benchmark": benchmark,
        "task_id": task_id,
        "answer_count": answer_count,
        "overall_reward": float(scores["overall_reward"]),
        "per_type": dict(scores.get("per_type") or {}),
    }
