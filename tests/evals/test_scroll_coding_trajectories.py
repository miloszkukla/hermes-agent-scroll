"""The coding lane is fixed, objective, and starts from failing workspaces."""

import pytest

from evals.scroll.coding_live import _items, _percentile, paired_bootstrap_lower_bound
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


def test_coding_workspace_starts_failing_and_reference_repair_is_not_present(tmp_path):
    trajectory = next(item for item in TRAJECTORIES if item.category == "render")
    write_workspace(trajectory, tmp_path)

    assert not verify_workspace(tmp_path)
    assert "LABEL:" not in (tmp_path / "app" / "render.py").read_text(encoding="utf-8")
    assert "return value.upper()" not in (tmp_path / "app" / "normalizer.py").read_text(encoding="utf-8")


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
