"""Credential-free deterministic evidence for the Scroll result adapter."""

import json
from pathlib import Path

from evals.scroll.fixtures import FIXTURES
from evals.scroll.result_adapter import normalize_result
from evals.scroll.runner import run_all


def test_scroll_fixture_manifest_and_recall_results_are_complete():
    manifest_path = Path("evals/scroll/manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results = run_all()

    assert manifest["live_model"] is False
    assert manifest["fixtures"] == [fixture.identifier for fixture in FIXTURES]
    assert [result["fixture"] for result in results] == manifest["fixtures"]
    assert all(result["ok"] for result in results)
    assert all(result["stats"]["hist_search"] == 1 for result in results)


def test_scroll_result_adapter_rejects_ambiguous_arms_and_shapes():
    row = normalize_result("scroll", {"fixture": "exact-value", "ok": True, "matches": 1, "stats": {}})

    assert row == {"schema_version": 1, "arm": "scroll", "fixture": "exact-value", "ok": True, "matches": 1, "stats": {}}
