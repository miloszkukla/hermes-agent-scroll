"""Hermes adaptation of the pinned Scroll LongMemEval ingest behavior."""

from evals.scroll.longmemeval import snapshot_from_sessions, to_iso_date
from plugins.context_engine.scroll.sandbox import ScrollCallbacks


def test_longmemeval_dates_are_normalized_without_ambiguous_fallbacks():
    assert to_iso_date("2024/03/15 (Fri) 09:30") == "2024-03-15"
    assert to_iso_date("2024/3/5") == "2024-03-05"
    assert to_iso_date("not a date") is None


def test_longmemeval_sessions_are_recallable_through_a_value_only_snapshot():
    snapshot = snapshot_from_sessions([
        {"date": "2024/03/15 (Fri) 09:30", "turns": [
            {"role": "user", "content": "Plan a Flask budget tracker."},
            {"role": "assistant", "content": "Use SQLite for storage."},
        ]},
        {"date": "2024/04/01", "turns": [{"role": "user", "content": "A later follow-up."}]},
    ], "qa-1")
    callbacks = ScrollCallbacks(lambda: snapshot)
    callbacks.rebind(snapshot)

    hits = callbacks.search("Flask budget tracker", scope="task", k=5, snippet=False)

    assert hits[0]["content"].startswith("[Session 1 | 2024-03-15]")
    assert snapshot.rows[0].session_id == "seed:qa-1:s1"
    assert snapshot.rows[0].correlation == (("dataset", "longmemeval"), ("session", "1"), ("date", "2024-03-15"))
