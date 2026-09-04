"""Contract tests for SessionDB's plugin-safe canonical history projection."""

from dataclasses import FrozenInstanceError

import pytest

from hermes_state import SessionDB


@pytest.fixture
def db(tmp_path):
    return SessionDB(tmp_path / "state.db")


def test_snapshot_is_immutable_redacted_and_storage_free(db):
    db.create_session("session", source="test")
    db.append_message("session", "user", "secret sk-abcdefghijklmnopqrstuvwxyz")
    db.append_message(
        "session", "assistant", [{"type": "image_url", "image_url": {"url": "data:image/png;base64,PRIVATE"}}],
    )
    db.append_message(
        "session", "assistant", "called a tool", tool_calls=[{
            "id": "call-1", "function": {"name": "lookup", "arguments": '{"secret":"must-not-leak"}'},
        }],
    )

    snapshot = db.get_canonical_history_snapshot("session")

    assert snapshot.lineage_id == "session"
    assert snapshot.high_water_mark == 3
    assert snapshot.generation == 0
    assert isinstance(snapshot.rows, tuple)
    assert "abcdefghijklmnopqrstuvwxyz" not in snapshot.rows[0].text
    assert snapshot.rows[1].fidelity == "degraded"
    assert snapshot.rows[1].content_reference.startswith("sha256:")
    assert "PRIVATE" not in snapshot.rows[1].text
    assert snapshot.rows[2].tool_calls[0].name == "lookup"
    assert "must-not-leak" not in repr(snapshot.rows[2].tool_calls[0])
    with pytest.raises(FrozenInstanceError):
        snapshot.rows[0].text = "mutated"


def test_snapshot_excludes_undone_rows_and_normalizes_compaction(db):
    db.create_session("session", source="test")
    db.append_messages_batch("session", [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "retained question"},
        {"role": "assistant", "content": "retained answer"},
    ])
    db.archive_and_compact("session", [
        {"role": "assistant", "content": "summary", "_compressed_summary": True},
        {"role": "user", "content": "retained question"},
        {"role": "assistant", "content": "retained answer"},
    ], tail_count=2)
    undone_id = db.append_message("session", "user", "undone")
    db._execute_write(lambda conn: conn.execute(
        "UPDATE messages SET active = 0, compacted = 0 WHERE id = ?", (undone_id,),
    ))

    snapshot = db.get_canonical_history_snapshot("session")
    texts = [row.text for row in snapshot.rows]

    assert texts == ["old question", "old answer", "summary", "retained question", "retained answer"]
    assert "undone" not in texts
    assert snapshot.high_water_mark == undone_id
    assert snapshot.generation == 1
    assert [row.order_key for row in snapshot.rows] == [
        (snapshot.generation, row._row_id) for row in snapshot.rows
    ]
    assert [row.is_compressed_summary for row in snapshot.rows] == [False, False, True, False, False]


def test_snapshot_generation_changes_only_at_a_committed_compaction(db):
    db.create_session("session", source="test")
    first_id = db.append_message("session", "user", "first")
    first = db.get_canonical_history_snapshot("session")
    db.append_message("session", "assistant", "second")
    appended = db.get_canonical_history_snapshot("session")

    assert first.generation == appended.generation == 0
    assert first.rows[0]._row_id == appended.rows[0]._row_id == first_id
    assert first.rows[0].order_key == appended.rows[0].order_key

    db.archive_and_compact("session", [{"role": "assistant", "content": "summary"}])
    compacted = db.get_canonical_history_snapshot("session")

    assert compacted.generation == 1
    assert compacted.high_water_mark > appended.high_water_mark
    assert all(row.generation == compacted.generation for row in compacted.rows)


def test_snapshot_reads_compression_lineage_but_not_explicit_branch(db):
    db.create_session("root", source="test")
    db.append_message("root", "user", "root history")
    db.create_session("continuation", source="test", parent_session_id="root")
    db.append_message("continuation", "assistant", "continued history")
    db.create_session("branch", source="test", parent_session_id="root", model_config={"_branched_from": "root"})
    db.append_message("branch", "user", "branch-only history")

    continuation = db.get_canonical_history_snapshot("continuation")
    branch = db.get_canonical_history_snapshot("branch")

    assert continuation.lineage_id == "root"
    assert [row.text for row in continuation.rows] == ["root history", "continued history"]
    assert branch.lineage_id == "branch"
    assert [row.text for row in branch.rows] == ["branch-only history"]


def test_snapshot_rotation_advances_generation_once_and_keeps_it_on_append(db):
    db.create_session("parent", source="test")
    db.append_message("parent", "user", "old history")
    db.publish_compression_child(
        parent_session_id="parent", child_session_id="child", source="test",
        messages=[{"role": "assistant", "content": "summary"}],
        require_compression_lease=False,
    )
    rotated = db.get_canonical_history_snapshot("child")
    db.append_message("child", "user", "new history")
    appended = db.get_canonical_history_snapshot("child")

    assert rotated.generation == appended.generation == 1


def test_snapshot_releases_its_consistent_read_transaction(db):
    db.create_session("session", source="test")
    db.append_message("session", "user", "history")

    db.get_canonical_history_snapshot("session")

    with db._read_ctx() as conn:
        assert conn.in_transaction is False
