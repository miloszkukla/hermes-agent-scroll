"""Hermes adaptation of the pinned Scroll BEAM ingest behavior."""

from evals.scroll.beam import clean_content, iter_sessions, iter_turns, snapshot_from_chat, to_iso_date
from plugins.context_engine.scroll.sandbox import ScrollCallbacks


def test_beam_markers_and_dates_are_normalized():
    assert clean_content('Help ->-> 1,1') == 'Help'
    assert to_iso_date('August-17-2024') == '2024-08-17'
    assert to_iso_date('invalid') is None


def test_beam_batch_date_propagates_to_every_snapshot_turn():
    chat = [{"batch_number": 7, "turns": [[
        {"role": "user", "content": "first", "id": 0, "time_anchor": "August-17-2024"},
        {"role": "assistant", "content": "second", "id": 1},
    ]]}]

    assert [turn['date'] for turn in iter_turns(chat)] == ['August-17-2024', 'August-17-2024']
    snapshot = snapshot_from_chat(chat, 'beam-1')
    callbacks = ScrollCallbacks(lambda: snapshot)
    callbacks.rebind(snapshot)

    hits = callbacks.search('second', scope='task', k=5, snippet=False)

    assert hits[0]['content'].startswith('[Session 7 | 2024-08-17]')
    assert snapshot.rows[1].correlation[-1] == ('date', '2024-08-17')


def test_beam_10m_plans_remain_distinct_sessions():
    chat = [{"plan-1": [{
        "batch_number": 1, "time_anchor": "January-01-2025",
        "turns": [[{"id": "one", "role": "user", "content": "first"}]],
    }]}, {"plan-2": [{
        "batch_number": 1, "time_anchor": "January-02-2025",
        "turns": [[{"id": "two", "role": "assistant", "content": "second"}]],
    }]}]

    assert [session for session, _ in iter_sessions(chat)] == ["plan-1", "plan-2"]
    assert [turn["session"] for turn in iter_turns(chat)] == ["plan-1", "plan-2"]
    snapshot = snapshot_from_chat(chat, "beam-10m")

    assert snapshot.rows[0].text.startswith("[Session plan-1 | 2025-01-01]")
    assert snapshot.rows[1].session_id.endswith(":splan-2")
