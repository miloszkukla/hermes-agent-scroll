"""Live-evaluation loaders keep benchmark gold outside the agent probe."""

import json
from contextlib import contextmanager

import pytest

from evals.scroll.hermes_live import LiveRunError, _auxiliary_usage, _prepare_coding_scenario, agent_prompt_sha256, load_beam_items, load_longmemeval_items


def test_longmemeval_loader_exposes_only_public_probe(tmp_path):
    dataset = tmp_path / "longmemeval_s"
    dataset.write_text(json.dumps([{
        "question_id": "case-1", "question_type": "temporal-reasoning", "question": "What changed?",
        "answer": "gold answer must stay private", "haystack_dates": ["2025/1/2"],
        "haystack_sessions": [[{"role": "user", "content": "The status is amber."}]],
    }]), encoding="utf-8")

    item = load_longmemeval_items(dataset, ["longmemeval/case-1"])[0]

    assert item.public_probe == {"id": "longmemeval/case-1", "type": "temporal-reasoning", "question": "What changed?"}
    assert "gold answer must stay private" not in json.dumps(item.public_probe)
    assert item.gold["answer"] == "gold answer must stay private"
    assert item.history[0]["content"].startswith("[Session 1 | 2025-01-02] user:")


def test_longmemeval_loader_retains_non_string_gold_values(tmp_path):
    dataset = tmp_path / "longmemeval_s"
    dataset.write_text(json.dumps([{
        "question_id": "case-2", "question_type": "single-session-user", "question": "How many?",
        "answer": 4, "haystack_dates": ["2025/1/2"],
        "haystack_sessions": [[{"role": "user", "content": "There are four."}]],
    }]), encoding="utf-8")

    assert load_longmemeval_items(dataset, ["longmemeval/case-2"])[0].gold["answer"] == 4


def test_beam_loader_exposes_only_public_probe(tmp_path):
    root = tmp_path / "100K" / "1"
    (root / "probing_questions").mkdir(parents=True)
    (root / "chat.json").write_text(json.dumps([{
        "batch_number": 1, "time_anchor": "January-01-2025",
        "turns": [[{"id": "message-1", "role": "user", "content": "The branch is amber."}]],
    }]), encoding="utf-8")
    (root / "probing_questions" / "probing_questions.json").write_text(json.dumps({
        "abstention": [{"question": "Which branch?", "rubric": ["private rubric"]}],
    }), encoding="utf-8")

    item = load_beam_items(tmp_path, ["beam/100K/1/abstention-0"])[0]

    assert item.public_probe == {"id": "beam/100K/1/abstention-0", "type": "abstention", "question": "Which branch?"}
    assert "private rubric" not in json.dumps(item.public_probe)
    assert item.gold["rubric"] == ["private rubric"]
    assert item.history[0]["content"].startswith("[Session 1 | 2025-01-01] user:")


def test_agent_prompt_has_a_stable_sha256():
    assert len(agent_prompt_sha256()) == 64
    assert agent_prompt_sha256() == agent_prompt_sha256()


def test_live_worker_counts_auxiliary_compression_usage():
    class Connection:
        def execute(self, _query, _params):
            return self

        def fetchone(self):
            return (12, 3)

    class Database:
        @contextmanager
        def _read_ctx(self):
            yield Connection()

    assert _auxiliary_usage(Database(), "session") == (12, 3)
    with pytest.raises(LiveRunError, match="auxiliary"):
        _auxiliary_usage(object(), "session")


def test_coding_scenarios_drive_manual_selection_and_cold_rebuild(tmp_path):
    class Compressor:
        def compress(self, history, *, force):
            assert force
            return [*history, {"role": "system", "content": "selected"}]

    class Agent:
        context_compressor = Compressor()

        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    original = Agent()
    history = [{"role": "user", "content": "task"}]
    selected_agent, selected_history = _prepare_coding_scenario(original, history, "manual-compaction", tmp_path, Agent)
    assert selected_agent is original
    assert selected_history[-1]["content"] == "selected"
    (tmp_path / "cache" / "scroll").mkdir(parents=True)
    rebuilt_agent, rebuilt_history = _prepare_coding_scenario(original, history, "cache-loss-resume", tmp_path, Agent)
    assert original.closed and rebuilt_agent is not original and rebuilt_history is history
    assert not (tmp_path / "cache" / "scroll").exists()
