"""Fail-closed orchestration shared by future authorized Scroll evaluations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .live_manifest import LiveManifestError, validate_live_manifest


class PairedRunError(RuntimeError):
    """A frozen paired evaluation cannot continue safely."""


_MODEL_PROBE_KEYS = ("id", "type", "question")
_USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_tokens")


def model_probe(probe: Mapping[str, Any]) -> dict[str, str]:
    """Return the sole task fields an arm may receive from a benchmark row."""
    result: dict[str, str] = {}
    for key in _MODEL_PROBE_KEYS:
        value = probe.get(key)
        if not isinstance(value, str) or not value:
            raise PairedRunError(f"probe.{key} must be a non-empty string")
        result[key] = value
    return result


def _expected_ids(manifest: Mapping[str, Any]) -> tuple[str, ...]:
    ids = tuple(item for dataset in manifest["datasets"] for item in dataset["item_ids"])
    if not ids or any(not isinstance(item, str) or not item for item in ids) or len(set(ids)) != len(ids):
        raise PairedRunError("manifest dataset item_ids must be non-empty and globally unique")
    return ids


def _usage(value: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, float | int]:
    raw = value.get("usage") or {}
    if not isinstance(raw, Mapping):
        raise PairedRunError("executor usage must be a mapping")
    usage: dict[str, float | int] = {}
    for key in _USAGE_KEYS:
        number = raw.get(key)
        if not isinstance(number, (int, float)) or isinstance(number, bool) or number < 0:
            raise PairedRunError(f"executor usage.{key} must be non-negative")
        usage[key] = number
    if usage["input_tokens"] > manifest["input_token_budget"]:
        raise PairedRunError("executor exceeded frozen input_token_budget")
    if usage["output_tokens"] > manifest["output_token_budget"]:
        raise PairedRunError("executor exceeded frozen output_token_budget")
    if usage["cache_read_tokens"] > manifest["cache_read_token_budget"]:
        raise PairedRunError("executor exceeded frozen cache_read_token_budget")
    return usage


def run_paired_evaluation(
    manifest: Mapping[str, Any], probes: Sequence[Mapping[str, Any]],
    execute: Callable[[str, Mapping[str, str]], Mapping[str, Any]],
    judge: Callable[[Mapping[str, Any], str], Mapping[str, Any]],
) -> dict[str, Any]:
    """Run symmetric arms without constructing providers or retaining gold data.

    ``execute`` owns approved Hermes/provider setup and receives a redacted
    model probe only. ``judge`` is invoked after each response and may inspect
    the trusted full benchmark row. This module never opens a provider, reads a
    credential, or writes raw histories, answers, or gold values to a report.
    """
    try:
        validate_live_manifest(dict(manifest))
    except LiveManifestError as exc:
        raise PairedRunError(str(exc)) from exc
    expected = _expected_ids(manifest)
    by_id = {str(probe.get("id")): probe for probe in probes}
    if tuple(by_id) != expected or len(by_id) != len(probes):
        raise PairedRunError("probes must match the manifest's complete ordered item_ids")
    def run_one(index: int, task_id: str, arm: str) -> tuple[int, dict[str, Any]]:
        probe = by_id[task_id]
        response = execute(arm, model_probe(probe))
        if not isinstance(response, Mapping) or not isinstance(response.get("answer"), str):
            raise PairedRunError("executor must return a string answer")
        verdict = judge(probe, response["answer"])
        if not isinstance(verdict, Mapping) or not isinstance(verdict.get("score"), (int, float)) or isinstance(verdict.get("score"), bool):
            raise PairedRunError("judge must return a numeric score")
        answer_digest = hashlib.sha256(response["answer"].encode("utf-8", errors="replace")).hexdigest()
        return index, {"task_id": task_id, "arm": arm, "score": float(verdict["score"]), "answer_sha256": answer_digest, "usage": _usage(response, manifest), "judge_usage": _usage(verdict, manifest)}

    jobs = [(index, task_id, arm) for index, (task_id, arm) in enumerate((task_id, arm) for task_id in expected for arm in ("stock", "scroll"))]
    rows_by_index = {}
    executor = ThreadPoolExecutor(max_workers=manifest["max_parallel_workers"])
    futures = []
    try:
        futures = [executor.submit(run_one, *job) for job in jobs]
        for future in as_completed(futures):
            index, row = future.result()
            rows_by_index[index] = row
    except Exception:
        for future in futures:
            future.cancel()
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    rows = [rows_by_index[index] for index, _, _ in jobs]
    manifest_digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"manifest_sha256": manifest_digest, "billing_mode": manifest["billing_mode"], "rows": rows}
