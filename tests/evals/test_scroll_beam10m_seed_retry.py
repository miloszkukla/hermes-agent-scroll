"""Retry-supervisor contracts for BEAM-10M baseline seed checkpoints."""

import threading
import time

import pytest

from plugins.context_engine.scroll.evidence import run_qwen_flash_beam10m_seed_retry as supervisor


def test_failed_conversation_requeues_and_backfills_the_worker_slot():
    attempts = {"1": 0, "2": 0, "3": 0}
    active, peak, events = 0, 0, []
    lock = threading.Lock()

    def prepare(conversation):
        nonlocal active, peak
        with lock:
            attempts[conversation] += 1
            events.append(("start", conversation, attempts[conversation]))
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        if conversation == "1" and attempts[conversation] == 1:
            raise RuntimeError("expected")
        return conversation

    completed = supervisor.run_seed_queue(["1", "2", "3"], workers=2, retries=1, prepare=prepare, progress=lambda *_args, **_kwargs: None)

    assert completed == {"2": "2", "3": "3", "1": "1"}
    assert attempts == {"1": 2, "2": 1, "3": 1}
    assert peak <= 2
    assert events[-1] == ("start", "1", 2)


def test_exhausted_conversation_drains_unrelated_work_before_raising():
    completed = []

    def prepare(conversation):
        if conversation == "1":
            raise RuntimeError("expected")
        completed.append(conversation)
        return conversation

    with pytest.raises(supervisor.beam.live.LiveRunError, match="retries exhausted after draining"):
        supervisor.run_seed_queue(["1", "2", "3"], workers=2, retries=1, prepare=prepare, progress=lambda *_args, **_kwargs: None)

    assert completed == ["2", "3"]


def test_queue_rejects_duplicate_conversations():
    with pytest.raises(supervisor.beam.live.LiveRunError, match="configuration is invalid"):
        supervisor.run_seed_queue(["1", "1"], workers=1, retries=0, prepare=lambda conversation: conversation, progress=lambda *_args, **_kwargs: None)
