"""The rebuildable Scroll cache persists only redacted canonical projections."""

import json
import stat

import pytest

from agent.context_engine import CanonicalHistoryRow, CanonicalHistorySnapshot
from plugins.context_engine.scroll.cache import ScrollCache
from plugins.context_engine.scroll.engine import ScrollContextEngine


def test_scroll_cache_is_private_and_contains_only_snapshot_fields(tmp_path):
    cache = ScrollCache(tmp_path / "cache" / "scroll")
    snapshot = CanonicalHistorySnapshot("lineage", 1, 1, (
        CanonicalHistoryRow(
            _row_id=1, generation=1, order_key=(1, 1), session_id="session", role="user",
            text="redacted value", content_reference=None, tool_name=None, tool_call_id=None,
            tool_calls=(), correlation=(), timestamp=1.0, sensitivity="redacted", fidelity="text",
            is_compressed_summary=False,
        ),
    ))

    cache.store(snapshot)

    metadata = cache.load_metadata("lineage")
    cache_file = next((tmp_path / "cache" / "scroll").glob("*.json"))
    assert metadata["high_water_mark"] == 1
    assert metadata["rows"][0]["text"] == "redacted value"
    assert metadata["fingerprint"]
    assert stat.S_IMODE(cache_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(cache_file.parent.stat().st_mode) == 0o700


def test_scroll_cache_rejects_stale_or_tampered_fingerprints(tmp_path):
    cache = ScrollCache(tmp_path / "cache" / "scroll")
    snapshot = CanonicalHistorySnapshot("lineage", 1, 1, ())

    cache.store(snapshot)
    cache_file = next((tmp_path / "cache" / "scroll").glob("*.json"))
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    payload["fingerprint"] = "stale"
    cache_file.write_text(json.dumps(payload), encoding="utf-8")

    assert cache.load_metadata("lineage") is None


def test_scroll_cache_rejects_a_symlinked_target_and_purges_only_the_lineage(tmp_path):
    cache = ScrollCache(tmp_path / "cache" / "scroll")
    snapshot = CanonicalHistorySnapshot("lineage", 1, 1, ())

    cache.store(snapshot)
    cache_file = next((tmp_path / "cache" / "scroll").glob("*.json"))
    cache_file.unlink()
    cache_file.symlink_to(tmp_path / "outside.json")

    assert cache.load_metadata("lineage") is None
    with pytest.raises(OSError, match="symlink"):
        cache.delete("lineage")
    cache_file.unlink()
    cache.store(snapshot)
    cache.delete("lineage")
    assert cache.load_metadata("lineage") is None


def test_scroll_engine_reconciles_cache_only_at_start_or_committed_boundary(tmp_path):
    engine = ScrollContextEngine()
    engine.on_session_start("session", hermes_home=str(tmp_path))
    snapshot = CanonicalHistorySnapshot("lineage", 1, 1, ())

    engine.on_canonical_history_snapshot(snapshot)
    cache_file = next((tmp_path / "cache" / "scroll").glob("*.json"))
    first_mtime = cache_file.stat().st_mtime_ns
    engine.on_canonical_history_snapshot(snapshot)

    assert cache_file.stat().st_mtime_ns == first_mtime
    engine.on_canonical_history_snapshot(CanonicalHistorySnapshot("lineage", 2, 2, ()))
    assert ScrollCache(tmp_path / "cache" / "scroll").load_metadata("lineage")["generation"] == 1
    engine.on_session_start("session", hermes_home=str(tmp_path), boundary_reason="compression")
    engine.on_canonical_history_snapshot(CanonicalHistorySnapshot("lineage", 2, 2, ()))
    assert ScrollCache(tmp_path / "cache" / "scroll").load_metadata("lineage")["generation"] == 2
    engine.on_session_reset()
    assert ScrollCache(tmp_path / "cache" / "scroll").load_metadata("lineage") is None
    engine.on_session_end("session", [])


def test_scroll_cache_lease_defers_a_non_owner_until_the_owner_ends(tmp_path):
    owner = ScrollContextEngine()
    contender = ScrollContextEngine()
    snapshot = CanonicalHistorySnapshot("lineage", 1, 1, (
        CanonicalHistoryRow(
            _row_id=1, generation=1, order_key=(1, 1), session_id="session", role="user",
            text="durable detail", content_reference=None, tool_name=None, tool_call_id=None,
            tool_calls=(), correlation=(), timestamp=None, sensitivity="normal", fidelity="text",
            is_compressed_summary=False,
        ),
    ))
    owner.on_session_start("session", hermes_home=str(tmp_path))
    contender.on_session_start("session", hermes_home=str(tmp_path))
    owner.on_canonical_history_snapshot(snapshot)
    contender.on_canonical_history_snapshot(snapshot)

    deferred = json.loads(contender.handle_tool_call("scroll_repl", {"source": "print(ms.search('durable'))"}))

    assert deferred == {"error": "RECALL DEFERRED: Scroll lineage is active elsewhere; retry later."}
    owner.on_session_end("session", [])
    resumed = json.loads(contender.handle_tool_call("scroll_repl", {"source": "print(ms.search('durable')[0]['content'])"}))
    assert resumed == {"stdout": "durable detail\n", "truncated": False}
    contender.on_session_end("session", [])


def test_scroll_cache_path_failure_keeps_selection_bounded_and_defers_recall(tmp_path):
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    (cache_root / "scroll").symlink_to(tmp_path / "missing-cache-target")
    engine = ScrollContextEngine()
    engine.on_session_start("session", hermes_home=str(tmp_path))
    engine.on_canonical_history_snapshot(CanonicalHistorySnapshot("lineage", 1, 1, ()))

    selected = engine.select_context([
        {"role": "system", "content": "policy"},
        {"role": "user", "content": "current request"},
    ], budget_tokens=8_000)
    deferred = json.loads(engine.handle_tool_call("scroll_repl", {"source": "print('unreachable')"}))

    assert selected[0]["content"] == "policy"
    assert deferred == {"error": "RECALL DEFERRED: Scroll lineage is active elsewhere; retry later."}
    engine.on_session_end("session", [])
