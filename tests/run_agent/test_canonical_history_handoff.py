"""The context-engine boundary must publish values, never SessionDB capability."""

from types import SimpleNamespace

from agent.conversation_compression import _adopt_live_compression_child
from agent.context_engine import CanonicalHistorySnapshot
from hermes_state import SessionDB
from run_agent import AIAgent


def test_snapshot_handoff_passes_only_the_immutable_projection():
    snapshot = CanonicalHistorySnapshot("lineage", 2, 2, ())

    class FakeDB:
        def __init__(self):
            self.requests = []

        def get_canonical_history_snapshot(self, session_id):
            self.requests.append(session_id)
            return snapshot

    class Engine:
        uses_canonical_history_snapshots = True

        def __init__(self):
            self.received = []

        def on_canonical_history_snapshot(self, value):
            self.received.append(value)

    agent = AIAgent.__new__(AIAgent)
    agent.context_compressor = Engine()
    agent._session_db = FakeDB()
    agent.session_id = "physical-session"

    agent._publish_canonical_history_snapshot()

    assert agent._session_db.requests == ["physical-session"]
    assert agent.context_compressor.received == [snapshot]
    assert not hasattr(agent.context_compressor, "_session_db")


def test_snapshot_engines_never_receive_session_db_at_compression_rotation(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    db.create_session("parent", source="cli")
    db.end_session("parent", "compression")
    db.create_session("child", source="cli", parent_session_id="parent")
    db.replace_messages("child", [{"role": "user", "content": "summary"}])

    class Engine:
        uses_canonical_history_snapshots = True

        def __init__(self):
            self.start_context = None

        def on_session_start(self, _session_id, **kwargs):
            self.start_context = kwargs

    engine = Engine()
    agent = SimpleNamespace(
        context_compressor=engine, session_id="parent", platform="cli", _gateway_session_key=None,
        _session_db_created=False, _last_flushed_db_idx=0, _flushed_db_message_session_id="",
        _flushed_db_message_ids=set(), _memory_manager=None,
    )

    recovered = _adopt_live_compression_child(agent, db, "parent")
    assert [(message["role"], message["content"]) for message in recovered] == [("user", "summary")]
    assert "session_db" not in engine.start_context
    assert engine.start_context["hermes_home"]


def test_recovered_compression_child_publishes_before_first_scroll_recall(tmp_path):
    from plugins.context_engine.scroll.engine import ScrollContextEngine

    db = SessionDB(db_path=tmp_path / "state.db")
    db.create_session("parent", source="cli")
    db.end_session("parent", "compression")
    db.create_session("child", source="cli", parent_session_id="parent")
    db.replace_messages("child", [{"role": "user", "content": "needle from recovered child"}])
    engine = ScrollContextEngine()
    agent = SimpleNamespace(
        context_compressor=engine, session_id="parent", platform="cli", _gateway_session_key=None,
        _session_db_created=False, _last_flushed_db_idx=0, _flushed_db_message_session_id="",
        _flushed_db_message_ids=set(), _memory_manager=None,
    )

    def publish_snapshot():
        engine.on_canonical_history_snapshot(db.get_canonical_history_snapshot(agent.session_id))

    agent._publish_canonical_history_snapshot = publish_snapshot
    try:
        recovered = _adopt_live_compression_child(agent, db, "parent")
        assert [(message["role"], message["content"]) for message in recovered] == [
            ("user", "needle from recovered child"),
        ]
        result = engine.handle_tool_call("scroll_repl", {"source": "print(ms.search('needle')[0]['content'])"})
        assert "needle from recovered child" in result
    finally:
        engine.on_session_end("child", [])
        db.close()
