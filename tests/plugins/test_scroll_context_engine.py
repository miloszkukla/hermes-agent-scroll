"""Focused integration coverage for the single-tool Monty Scroll adapter."""

import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent.context_engine import CanonicalHistoryRow, CanonicalHistorySnapshot, CanonicalHistoryToolCall
from agent.conversation_loop import _apply_context_engine_selection
from hermes_state import SessionDB
from plugins.context_engine.scroll.engine import SCROLL_PROTOCOL, ScrollContextEngine
from plugins.context_engine.scroll.sandbox import (
    E2E_WORKER_CRASH_SOURCE, MAX_ROWS, MAX_SQL_CONTENT_BYTES, MAX_SQL_METADATA_BYTES,
    MAX_SQL_PROJECTION_BYTES, MAX_SQL_PROJECTION_ROWS,
)
from plugins.context_engine.scroll.eviction_index import EvictionIndex, Leaf


def _snapshot(generation=4, row_id=4):
    return CanonicalHistorySnapshot("lineage", generation, generation, (
        CanonicalHistoryRow(
            _row_id=row_id, generation=generation, order_key=(generation, row_id), session_id="session",
            role="user", text="needle details", content_reference=None, tool_name=None,
            tool_call_id=None, tool_calls=(), correlation=(), timestamp=1.0,
            sensitivity="normal", fidelity="text", is_compressed_summary=False,
        ),
    ))


def _call(engine, source):
    return json.loads(engine.handle_tool_call("scroll_repl", {"source": source}))


def test_scroll_exposes_only_the_monty_repl_and_keeps_namespace():
    engine = ScrollContextEngine()
    engine.on_canonical_history_snapshot(_snapshot())
    assert [schema["name"] for schema in engine.get_tool_schemas()] == ["scroll_repl"]

    first = _call(engine, "values = [n * n for n in range(5)]\nprint(ms.search('needle')[0]['content'])")
    second = _call(engine, "print(values[-1], ms.expand([4])[0]['content'], ms.session_id, ms.task_id)")

    assert first == {"stdout": "needle details\n", "truncated": False}
    assert second == {"stdout": "16 needle details session lineage\n", "truncated": False}
    engine.on_session_end("session", [])


def test_scroll_callbacks_reject_writes_and_only_stale_replaced_navigation_handles():
    engine = ScrollContextEngine()
    engine.on_canonical_history_snapshot(_snapshot())
    assert _call(engine, "seq = ms.search('needle')[0]['seq']")["stdout"] == ""
    engine.on_canonical_history_snapshot(_snapshot(generation=5))
    stale = _call(engine, "ms.expand([seq])")
    assert stale["namespace_reset"] is True
    assert "stale sequence handle" in stale["error"]
    assert _call(engine, "seq = ms.search('needle')[0]['seq']; print(ms.expand([seq])[0]['content'])")["stdout"] == "needle details\n"
    engine.on_canonical_history_snapshot(_snapshot(generation=5, row_id=5))
    stale = _call(engine, "ms.expand([seq])")
    assert stale["namespace_reset"] is True
    assert "stale sequence handle" in stale["error"]
    assert "read-only SELECT" in _call(engine, "ms.sql_query('DELETE FROM history')")["error"]
    assert "bounded scalar" in _call(engine, "ms.sql_query('SELECT content FROM history', [[1]])")["error"]
    engine.on_session_end("session", [])


def test_scroll_generation_boundary_requires_a_fresh_search_after_compaction(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    engine = ScrollContextEngine()
    try:
        db.create_session("session", source="test")
        db.append_message("session", "user", "needle archived detail")
        engine.on_canonical_history_snapshot(db.get_canonical_history_snapshot("session"))
        assert _call(engine, "seq = ms.search('needle')[0]['seq']")["stdout"] == ""

        db.archive_and_compact("session", [{"role": "assistant", "content": "summary", "_compressed_summary": True}])
        engine.on_canonical_history_snapshot(db.get_canonical_history_snapshot("session"))

        stale = _call(engine, "ms.expand([seq])")
        assert stale["namespace_reset"] is True
        assert "stale sequence handle" in stale["error"]
        assert _call(engine, "seq = ms.search('needle')[0]['seq']; print(ms.expand([seq])[0]['content'])")["stdout"] == "needle archived detail\n"
    finally:
        engine.on_session_end("session", [])
        db.close()


def test_scroll_reset_and_end_discard_the_namespace_and_prior_lineage():
    engine = ScrollContextEngine()
    engine.on_canonical_history_snapshot(_snapshot())
    assert _call(engine, "saved = 'must not survive reset'") == {"stdout": "", "truncated": False}

    engine.on_session_reset()
    replacement = CanonicalHistorySnapshot("replacement", 0, 1, (
        CanonicalHistoryRow(
            _row_id=1, generation=0, order_key=(0, 1), session_id="replacement", role="user",
            text="new lineage", content_reference=None, tool_name=None, tool_call_id=None,
            tool_calls=(), correlation=(), timestamp=None, sensitivity="normal", fidelity="text",
            is_compressed_summary=False,
        ),
    ))
    engine.on_canonical_history_snapshot(replacement)

    assert _call(engine, "print(ms.search('needle'))") == {"stdout": "[]\n", "truncated": False}
    stale = _call(engine, "print(saved)")
    assert stale["namespace_reset"] is True
    engine.on_session_end("replacement", [])
    assert engine.working_memory_digest() == ""


def test_scroll_worker_crash_discards_the_worker_and_recovers_from_canonical_history(monkeypatch):
    engine = ScrollContextEngine()
    engine.on_canonical_history_snapshot(_snapshot())
    try:
        assert _call(engine, "print(ms.search('needle')[0]['content'])")["stdout"] == "needle details\n"
        worker_pid = engine._repl._session.worker_pid
        monkeypatch.setenv("HERMES_SCROLL_E2E_WORKER_CRASH", "1")

        crashed = _call(engine, E2E_WORKER_CRASH_SOURCE)

        assert crashed["namespace_reset"] is True
        assert "monty worker crashed" in crashed["error"]
        assert engine._repl._session is None
        recovered = _call(engine, "print(ms.search('needle')[0]['content'])")
        assert recovered == {"stdout": "needle details\n", "truncated": False}
        assert engine._repl._session.worker_pid != worker_pid
    finally:
        engine.on_session_end("session", [])


def test_scroll_selection_failure_stays_bounded_at_the_host_call_site(monkeypatch):
    engine = ScrollContextEngine()
    engine.context_length = 8_000
    request = [
        {"role": "system", "content": "policy"},
        {"role": "user", "content": "old detail " * 5_000},
        {"role": "user", "content": "current task " * 5_000},
    ]

    def fail(*args, **kwargs):
        raise RuntimeError("injected selection failure")

    monkeypatch.setattr(engine, "_bounded_context", fail)
    selected = _apply_context_engine_selection(
        SimpleNamespace(context_compressor=engine, session_id="session"), request, request[1:], request[-1], logger=MagicMock(),
    )

    assert selected is not request
    assert selected[:2] == [request[0], {"role": "system", "content": SCROLL_PROTOCOL}]
    assert selected[-1]["role"] == "user"
    assert selected[-1]["content"].startswith("[earlier task detail truncated]")
    assert "old detail" not in selected[-1]["content"]
    assert sum(engine._message_tokens(message) for message in selected) <= engine._input_target(8_000)


def test_scroll_compaction_is_pure_and_does_not_start_a_worker():
    engine = ScrollContextEngine()
    messages = [{"role": "system", "content": "policy"}] + [
        {"role": "user" if i % 2 else "assistant", "content": str(i)} for i in range(20)
    ]

    selected = engine.compress(messages, force=True)

    assert selected[0] is messages[0]
    assert selected[1]["role"] == "system"
    assert selected[1] == {"role": "system", "content": SCROLL_PROTOCOL}
    assert "context compressed" in selected[2]["content"]
    assert selected[3:] == messages[-engine.protect_last_n:]
    assert engine._repl._pool is None


def test_scroll_compaction_renders_model_headlines_with_canonical_sequence_ids():
    engine = ScrollContextEngine()
    snapshot = CanonicalHistorySnapshot("lineage", 4, 20, tuple(
        CanonicalHistoryRow(
            _row_id=index, generation=4, order_key=(4, index), session_id="session",
            role="assistant" if index == 4 else "user", text="⟦ deployed stable release ⟧" if index == 4 else str(index),
            content_reference=None, tool_name=None, tool_call_id=None, tool_calls=(), correlation=(), timestamp=None,
            sensitivity="normal", fidelity="text", is_compressed_summary=False,
        ) for index in range(1, 21)
    ))
    messages = [{"role": "system", "content": "policy"}] + [
        {"role": "assistant" if index == 4 else "user", "content": "⟦ deployed stable release ⟧" if index == 4 else str(index)}
        for index in range(1, 21)
    ]
    engine.on_canonical_history_snapshot(snapshot)

    selected = engine.compress(messages, force=True)

    assert "Canonical generation 4" in selected[2]["content"]
    assert "seq 4  ⟦ deployed stable release ⟧" in selected[2]["content"]
    assert engine._repl._pool is None


def test_scroll_compaction_records_one_contiguous_eviction_boundary():
    engine = ScrollContextEngine()
    snapshot = CanonicalHistorySnapshot("lineage", 4, 36, tuple(
        CanonicalHistoryRow(
            _row_id=index, generation=4, order_key=(4, index), session_id="session",
            role="assistant", text=f"⟦ milestone {index} ⟧", content_reference=None, tool_name=None,
            tool_call_id=None, tool_calls=(), correlation=(), timestamp=None,
            sensitivity="normal", fidelity="text", is_compressed_summary=False,
        ) for index in range(1, 37)
    ))
    messages = [{"role": "system", "content": "policy"}] + [
        {"role": "assistant", "content": f"⟦ milestone {index} ⟧"} for index in range(1, 37)
    ]
    engine.on_canonical_history_snapshot(snapshot)

    selected = engine.compress(messages, force=True)

    assert "[L0] seq 1–28" in selected[2]["content"]
    assert "[L1]" not in selected[2]["content"]
    assert "seq 1  ⟦ milestone 1 ⟧" in selected[2]["content"]
    assert "seq 28  ⟦ milestone 28 ⟧" in selected[2]["content"]
    assert "milestone 29" not in selected[2]["content"]
    assert engine._repl._pool is None


def test_scroll_selection_adds_boundaries_once_and_is_retry_idempotent():
    engine = ScrollContextEngine()
    snapshot = CanonicalHistorySnapshot("lineage", 1, 36, tuple(
        CanonicalHistoryRow(
            _row_id=index, generation=1, order_key=(1, index), session_id="session",
            role="assistant", text=f"⟦ milestone {index} ⟧", content_reference=None, tool_name=None,
            tool_call_id=None, tool_calls=(), correlation=(), timestamp=None,
            sensitivity="normal", fidelity="text", is_compressed_summary=False,
        ) for index in range(1, 37)
    ))
    messages = [{"role": "assistant", "content": f"⟦ milestone {index} ⟧"} for index in range(1, 37)]
    engine.on_canonical_history_snapshot(snapshot)

    first = engine._eviction_placeholder([], messages[20:], record_boundary=True)["content"]
    second = engine._eviction_placeholder([], messages[28:], record_boundary=True)["content"]
    retry = engine._eviction_placeholder([], messages[28:], record_boundary=True)["content"]

    assert "[L0] seq 1–20" in first
    assert "[L0] seq 1–20" in second
    assert "[L0] seq 21–28" in second
    assert retry == second


def test_scroll_compaction_matches_duplicate_tail_rows_from_the_newest_snapshot_end():
    engine = ScrollContextEngine()
    snapshot = CanonicalHistorySnapshot("lineage", 4, 12, tuple(
        CanonicalHistoryRow(
            _row_id=index, generation=4, order_key=(4, index), session_id="session",
            role="user", text="repeated", content_reference=None, tool_name=None,
            tool_call_id=None, tool_calls=(), correlation=(), timestamp=None,
            sensitivity="normal", fidelity="text", is_compressed_summary=False,
        ) for index in range(1, 13)
    ))
    messages = [{"role": "system", "content": "policy"}] + [
        {"role": "user", "content": "repeated"} for _ in range(12)
    ]
    engine.on_canonical_history_snapshot(snapshot)

    selected = engine.compress(messages, force=True)

    assert "[L0] seq 1–4" in selected[2]["content"]
    assert "seq 9–12" not in selected[2]["content"]


def test_scroll_eviction_index_carries_without_losing_sequence_spans():
    index = EvictionIndex()
    for sequence_id in range(1, 26):
        index.add_eviction([Leaf(sequence_id, f"milestone {sequence_id}")], seq_lo=sequence_id, seq_hi=sequence_id)

    assert all(len(level) < 5 for level in index._levels)
    rendered = "\n".join(index.render())
    assert "[L2] seq 1–16" in rendered
    assert "[L1] seq 17–20" in rendered
    assert "[L0] seq 25–25" in rendered


def test_scroll_selection_keeps_policies_protocol_and_whole_tool_group():
    engine = ScrollContextEngine()
    request = [
        {"role": "system", "content": "policy"},
        {"role": "user", "content": "old " * 2_000},
        {"role": "assistant", "content": "tool call", "tool_calls": [{"id": "call"}]},
        {"role": "tool", "content": "tool result"},
        {"role": "user", "content": "current task"},
    ]

    selected = engine.select_context(request, budget_tokens=8_000)

    assert selected[:2] == [request[0], {"role": "system", "content": SCROLL_PROTOCOL}]
    assert "context compressed" in selected[2]["content"]
    assert selected[-1] is request[-1]
    assert any(message is request[2] for message in selected) == any(message is request[3] for message in selected)


def test_scroll_selection_merges_only_the_uncommitted_recall_suffix():
    engine = ScrollContextEngine()
    engine.on_canonical_history_snapshot(_snapshot())
    pending = {"role": "user", "content": "pending recall detail"}
    conversation = [
        {"role": "user", "content": "needle details", "_db_persisted": True, "_row_id": 4},
        pending,
    ]

    engine.select_context(
        [{"role": "system", "content": "policy"}, pending], conversation_messages=conversation,
        incoming_message=dict(pending), budget_tokens=8_000,
    )

    assert _call(engine, "print(ms.search('pending')[0]['seq'], ms.search('pending')[0]['content'])") == {
        "stdout": "5 pending recall detail\n", "truncated": False,
    }
    assert [row._row_id for row in engine._snapshot.rows] == [4]
    engine.select_context(
        [{"role": "system", "content": "policy"}],
        conversation_messages=[{"role": "user", "content": "concurrent durable detail", "_db_persisted": True, "_row_id": 5}],
        budget_tokens=8_000,
    )
    assert _call(engine, "print(ms.search('concurrent')[0]['seq'])") == {"stdout": "5\n", "truncated": False}
    engine.on_session_end("session", [])


def test_scroll_selection_reserves_the_recovery_map_and_truncates_only_the_current_task():
    engine = ScrollContextEngine()
    request = [
        {"role": "system", "content": "policy"},
        {"role": "user", "content": "old task detail " * 800},
        {"role": "assistant", "content": "call", "tool_calls": [{"id": "call-1"}]},
        {"role": "tool", "tool_call_id": "call-1", "content": "large tool output " * 800},
        {"role": "user", "content": "current task detail " * 800},
    ]

    selected = engine.select_context(request, budget_tokens=8_000)

    assert selected[:2] == [request[0], {"role": "system", "content": SCROLL_PROTOCOL}]
    assert "context compressed" in selected[2]["content"]
    assert request[2] not in selected and request[3] not in selected
    assert selected[-1]["role"] == "user"
    assert selected[-1]["content"].startswith("[earlier task detail truncated]")
    assert sum(engine._message_tokens(message) for message in selected) <= engine._input_target(8_000)


def test_scroll_redacts_repl_egress():
    engine = ScrollContextEngine()
    engine.on_canonical_history_snapshot(_snapshot())

    result = _call(engine, "print('sk-abcdefghijklmnopqrstuvwxyz')")

    assert "abcdefghijklmnopqrstuvwxyz" not in result["stdout"]
    engine.on_session_end("session", [])


def test_scroll_search_degrades_to_a_deterministic_scan_without_fts5():
    engine = ScrollContextEngine()
    engine.on_canonical_history_snapshot(_snapshot())

    assert _call(engine, "print(ms.search('needle')[0]['content'])") == {"stdout": "needle details\n", "truncated": False}
    assert engine._callbacks._fts_available is True
    engine._callbacks._fts_available = False
    assert _call(engine, "print(ms.search('needle')[0]['content'])") == {"stdout": "needle details\n", "truncated": False}
    engine.on_session_end("session", [])


def test_scroll_sql_authorizer_and_bound_params_preserve_canonical_history():
    engine = ScrollContextEngine()
    engine.on_canonical_history_snapshot(_snapshot())

    selected = _call(engine, "print(ms.sql_query('SELECT content FROM history WHERE content = ?', ['needle details']))")
    named = _call(engine, "print(ms.sql_query('SELECT content FROM history WHERE content = :value', {'value': 'needle details'}))")
    hostile = _call(engine, "print(ms.sql_query('SELECT content FROM history WHERE content = ?', [\"needle details' OR 1=1 --\"]))")
    denied = _call(engine, "ms.sql_query('ATTACH DATABASE \\\'x\\\' AS other')")
    preserved = _call(engine, "print(ms.sql_query('SELECT count(*) AS n FROM history')[0]['n'])")

    assert selected == {"stdout": "[{'content': 'needle details'}]\n", "truncated": False}
    assert named == selected
    assert hostile == {"stdout": "[]\n", "truncated": False}
    assert "read-only SELECT" in denied["error"]
    assert "fixed history table" in _call(engine, "ms.sql_query(\"SELECT 'history'\")")["error"]
    assert preserved == {"stdout": "1\n", "truncated": False}
    engine.on_session_end("session", [])


def test_scroll_sql_bounds_host_values_and_rejects_allocation_functions():
    engine = ScrollContextEngine()
    snapshot = CanonicalHistorySnapshot("lineage", 1, 1, (
        CanonicalHistoryRow(
            _row_id=1, generation=1, order_key=(1, 1), session_id="session", role="user",
            text="x" * (MAX_SQL_CONTENT_BYTES * 1_024), content_reference=None, tool_name=None, tool_call_id=None,
            tool_calls=(), correlation=(), timestamp=1.0, sensitivity="normal", fidelity="text",
            is_compressed_summary=False,
        ),
    ))
    engine.on_canonical_history_snapshot(snapshot)

    assert engine._callbacks.sql_query("SELECT length(content) AS length FROM history") == [
        {"length": MAX_SQL_CONTENT_BYTES},
    ]
    assert engine._callbacks.sql_query("SELECT content FROM history") == [
        {"content": "x" * MAX_SQL_CONTENT_BYTES},
    ]
    with pytest.raises(sqlite3.DataError, match="string or blob too big"):
        engine._callbacks.sql_query("SELECT content || content || content || content || content FROM history")
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        engine._callbacks.sql_query("SELECT printf('%1000000000s', 'x') FROM history")

    engine.on_canonical_history_snapshot(CanonicalHistorySnapshot("lineage", 2, 2, tuple(
        CanonicalHistoryRow(
            _row_id=index, generation=2, order_key=(2, index), session_id="s" * MAX_SQL_METADATA_BYTES,
            role="u" * MAX_SQL_METADATA_BYTES, text="x" * MAX_SQL_CONTENT_BYTES,
            content_reference=None, tool_name="t" * MAX_SQL_METADATA_BYTES,
            tool_call_id="c" * MAX_SQL_METADATA_BYTES, tool_calls=(), correlation=(), timestamp=1.0,
            sensitivity="n" * MAX_SQL_METADATA_BYTES, fidelity="f" * MAX_SQL_METADATA_BYTES,
            is_compressed_summary=False,
        ) for index in range(1, MAX_SQL_PROJECTION_ROWS * 2 + 1)
    )))
    projection = engine._callbacks.sql_query("SELECT count(*) AS rows, sum(length(content)) AS bytes FROM history")[0]
    assert 0 < projection["rows"] < MAX_SQL_PROJECTION_ROWS
    assert projection["bytes"] <= MAX_SQL_PROJECTION_BYTES
    rows = engine._callbacks.sql_query("SELECT seq FROM history")
    assert len(rows) == MAX_ROWS + 1
    assert rows[-1] == {"_truncated": True, "_row_cap": MAX_ROWS}

    engine.on_session_end("session", [])


def test_scroll_failure_is_never_presented_as_empty_history():
    engine = ScrollContextEngine()
    engine.on_canonical_history_snapshot(_snapshot())

    result = _call(engine, "raise ValueError('boom')")

    assert result["namespace_reset"] is True
    assert result["error"].startswith("RECALL FAILED: canonical history was NOT read")
    assert _call(engine, "print(ms.search('needle')[0]['content'])") == {
        "stdout": "needle details\n", "truncated": False,
    }
    engine.on_session_end("session", [])


def test_scroll_recall_excludes_its_own_source_and_output():
    rows = (
        CanonicalHistoryRow(
            _row_id=1, generation=1, order_key=(1, 1), session_id="session", role="user",
            text="the durable deployment detail", content_reference=None, tool_name=None,
            tool_call_id=None, tool_calls=(), correlation=(), timestamp=None,
            sensitivity="normal", fidelity="text", is_compressed_summary=False,
        ),
        CanonicalHistoryRow(
            _row_id=2, generation=1, order_key=(1, 2), session_id="session", role="assistant",
            text="print(ms.search('deployment'))", content_reference=None, tool_name=None,
            tool_call_id=None, tool_calls=(CanonicalHistoryToolCall("scroll_repl", "call-1", "sha256:source"),),
            correlation=(), timestamp=None, sensitivity="normal", fidelity="text", is_compressed_summary=False,
        ),
        CanonicalHistoryRow(
            _row_id=3, generation=1, order_key=(1, 3), session_id="session", role="tool",
            text="deployment search result", content_reference=None, tool_name="scroll_repl",
            tool_call_id="call-1", tool_calls=(), correlation=(), timestamp=None,
            sensitivity="normal", fidelity="text", is_compressed_summary=False,
        ),
    )
    engine = ScrollContextEngine()
    engine.on_canonical_history_snapshot(CanonicalHistorySnapshot("lineage", 1, 3, rows))

    assert _call(engine, "print(ms.search('deployment', k=10))")["stdout"] == "[{'seq': 1, 'generation': 1, 'role': 'user', 'kind': 'user', 'name': None, 'content': 'the durable deployment detail', 'score': 1, 'fidelity': 'text'}]\n"
    assert _call(engine, "print(ms.sql_query('SELECT seq FROM history ORDER BY seq'))")["stdout"] == "[{'seq': 1}]\n"
    assert _call(engine, "print(ms.expand([2, 3]))")["stdout"] == "[]\n"
    engine.on_session_end("session", [])


def test_scroll_working_memory_digest_has_no_values_or_checkout_state():
    engine = ScrollContextEngine()
    engine.on_canonical_history_snapshot(_snapshot())

    assert _call(engine, "secret = 'must-not-leak'\nvalues = [1, 2, 3]\ndef rank():\n    return values[0]") == {"stdout": "", "truncated": False}
    assert engine.working_memory_digest() == "rank:function:None\nsecret:str:13\nvalues:list:3\n"
    engine.on_session_end("session", [])
