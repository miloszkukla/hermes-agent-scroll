"""The coding lane is fixed, objective, and starts from failing workspaces."""

import hashlib
import json
from pathlib import Path

import pytest

from evals.scroll.coding_live import _items, _percentile, _resume_attestation, _resumable_coding_result, paired_bootstrap_lower_bound
from evals.scroll.coding_trajectories import CANONICAL_HISTORY_MIN_TOKENS, TRAJECTORIES, canonical_history_tokens, verify_workspace, write_workspace
from evals.scroll.hermes_live import LiveRunError


def test_coding_trajectories_are_complete_and_cover_required_scenarios():
    assert len(TRAJECTORIES) == 20
    assert len({item.identifier for item in TRAJECTORIES}) == 20
    assert {item.scenario for item in TRAJECTORIES} == {"automatic-compaction", "manual-compaction", "cache-loss-resume"}
    assert {item.category for item in TRAJECTORIES} == {"labels", "flags", "limits", "routes", "render"}
    assert all(len(item.history()) > 100 for item in TRAJECTORIES)
    assert all(canonical_history_tokens(item) >= CANONICAL_HISTORY_MIN_TOKENS for item in TRAJECTORIES)
    assert all(any(message["role"] == "tool" for message in item.history()) for item in TRAJECTORIES)
    assert all(sum(bool(message.get("tool_calls")) for message in item.history()) == 2 for item in TRAJECTORIES)
    assert all(all(call["type"] == "function" and call["function"]["name"] == "terminal" and call["function"]["arguments"] for message in item.history() for call in message.get("tool_calls", [])) for item in TRAJECTORIES)


def test_coding_workspace_starts_failing_and_reference_repair_is_not_present(tmp_path):
    trajectory = next(item for item in TRAJECTORIES if item.category == "render")
    write_workspace(trajectory, tmp_path)

    assert not verify_workspace(tmp_path)
    assert "LABEL:" not in (tmp_path / "app" / "render.py").read_text(encoding="utf-8")
    assert "return value.upper()" not in (tmp_path / "app" / "normalizer.py").read_text(encoding="utf-8")


def test_coding_workspace_verifier_does_not_mutate_the_workspace(tmp_path):
    trajectory = next(item for item in TRAJECTORIES if item.category == "labels")
    write_workspace(trajectory, tmp_path)
    (tmp_path / "app" / "labels.py").write_text("def render(value):\n    return '|'.join(part.strip().lower() for part in value.split(','))\n", encoding="utf-8")
    before = {path.relative_to(tmp_path): path.read_bytes() if path.is_file() else None for path in tmp_path.rglob("*")}

    assert verify_workspace(tmp_path)
    assert {path.relative_to(tmp_path): path.read_bytes() if path.is_file() else None for path in tmp_path.rglob("*")} == before


def test_coding_manifest_requires_the_exact_fixed_ordered_set():
    manifest = {"datasets": [{"name": "coding-trajectories", "item_ids": [item.identifier for item in TRAJECTORIES]}]}

    assert _items(manifest) == TRAJECTORIES
    manifest["datasets"][0]["item_ids"].reverse()
    with pytest.raises(LiveRunError, match="complete fixed ordered"):
        _items(manifest)


def test_coding_statistics_are_paired_and_deterministic():
    assert paired_bootstrap_lower_bound([0.25] * 20, seed=7) == 0.25
    assert paired_bootstrap_lower_bound([-0.1] * 20, seed=7) == -0.1
    assert _percentile([0.1, 0.2, 0.3, 0.4, 0.5], 0.95) == 0.5


def test_coding_resume_accepts_only_complete_bounded_worker_results(tmp_path, monkeypatch):
    root = tmp_path / "r4"
    result = root / "jobs" / "job" / "result.json"
    result.parent.mkdir(parents=True)
    result.write_text(json.dumps({"answer": "done", "usage": {"input_tokens": 1, "output_tokens": 2, "cache_read_tokens": 3}, "scenario_latency_seconds": 0.5}), encoding="utf-8")
    manifest = {"input_token_budget": 10, "output_token_budget": 10, "cache_read_token_budget": 10}
    attestation = {"jobs": {"job": {"runtime_root_name": "r4", "result_sha256": "a" * 64, "workspace_sha256": "b" * 64}}}
    monkeypatch.setattr("evals.scroll.coding_live.verify_workspace", lambda _workspace: True)
    monkeypatch.setattr("evals.scroll.coding_live._sha256_file", lambda _path: "a" * 64)
    monkeypatch.setattr("evals.scroll.coding_live._workspace_sha256", lambda _path: "b" * 64)

    assert _resumable_coding_result({"r4": root}, manifest, attestation, "job") == {"answer": "verified-pass", "usage": {"input_tokens": 1, "output_tokens": 2, "cache_read_tokens": 3}, "elapsed_seconds": None, "scenario_latency_seconds": 0.5, "resumed": True}
    assert _resumable_coding_result({"r4": root}, manifest, attestation, "unlisted") is None
    result.write_text(json.dumps({"answer": "", "usage": {"input_tokens": 1, "output_tokens": 2, "cache_read_tokens": 3}, "scenario_latency_seconds": 0.5}), encoding="utf-8")
    assert _resumable_coding_result({"r4": root}, manifest, attestation, "job") is None


def test_coding_resume_rejects_tampered_artifacts(tmp_path, monkeypatch):
    root = tmp_path / "r4"
    result = root / "jobs" / "job" / "result.json"
    result.parent.mkdir(parents=True)
    result.write_text(json.dumps({"answer": "done", "usage": {"input_tokens": 1, "output_tokens": 2, "cache_read_tokens": 3}, "scenario_latency_seconds": 0.5}), encoding="utf-8")
    manifest = {"input_token_budget": 10, "output_token_budget": 10, "cache_read_token_budget": 10}
    attestation = {"jobs": {"job": {"runtime_root_name": "r4", "result_sha256": "a" * 64, "workspace_sha256": "b" * 64}}}
    monkeypatch.setattr("evals.scroll.coding_live._sha256_file", lambda _path: "c" * 64)

    with pytest.raises(LiveRunError, match="does not match"):
        _resumable_coding_result({"r4": root}, manifest, attestation, "job")


def test_coding_resume_attestation_binds_the_frozen_source(tmp_path, monkeypatch):
    source = {"manifest_sha256": "a" * 64, "implementation_commit": "b" * 40, "runtime_root_name": "r4", "context_total_ceiling_seconds": 900, "auxiliary_compression_timeout_seconds": 300, "worker_timeout_seconds": 1200, "worker_access_token_minimum_ttl_seconds": 1260}
    attestation = {"schema_version": 1, **source, "jobs": {}}
    path = tmp_path / "attestation.json"
    path.write_text(json.dumps(attestation), encoding="utf-8")
    manifest = {"resume_sources": {"r4": {**source, "attestation_file": "attestation.json", "attestation_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}}
    monkeypatch.setattr("evals.scroll.coding_live._RESUME_ATTESTATION_DIRECTORY", Path("."))

    assert _resume_attestation(manifest, tmp_path) == {"jobs": {}}
    manifest["resume_sources"] = {"r4": {**manifest["resume_sources"]["r4"], "worker_timeout_seconds": 1201}}
    with pytest.raises(LiveRunError, match="does not match"):
        _resume_attestation(manifest, tmp_path)
