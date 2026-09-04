"""Live-evaluation loaders keep benchmark gold outside the agent probe."""

import json
import subprocess
from contextlib import contextmanager

import pytest

from evals.scroll.hermes_live import LiveRunError, _auxiliary_usage, _build_live_agent, _enabled_toolsets, _prepare_coding_scenario, _require_clean_git_checkout, agent_prompt_sha256, load_beam_items, load_longmemeval_items


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


def test_live_agent_uses_openrouter_chat_completions_for_seeded_runs():
    captured = _build_live_agent(lambda **kwargs: kwargs, {"model": "openai/gpt-5.6-luna", "max_iterations": 8, "max_output_tokens": 4096, "seed": 20260904}, "session", object(), ["coding"])

    assert captured["provider"] == "openrouter"
    assert captured["api_mode"] == "chat_completions"
    assert captured["request_overrides"] == {"seed": 20260904}


def test_coding_scenarios_drive_manual_selection_and_cold_rebuild(tmp_path):
    class Agent:
        def __init__(self):
            self.closed = False

        def _compress_context(self, history, system_message, *, force):
            assert force
            assert system_message == "coding prompt"
            return [*history, {"role": "system", "content": "selected"}], "rebuilt prompt"

        def close(self):
            self.closed = True

    original = Agent()
    history = [{"role": "user", "content": "task"}]
    selected_agent, selected_history = _prepare_coding_scenario(original, history, "coding prompt", "manual-compaction", tmp_path, Agent)
    assert selected_agent is original
    assert selected_history[-1]["content"] == "selected"
    (tmp_path / "cache" / "scroll").mkdir(parents=True)
    rebuilt_agent, rebuilt_history = _prepare_coding_scenario(original, history, "coding prompt", "cache-loss-resume", tmp_path, Agent)
    assert original.closed and rebuilt_agent is not original and rebuilt_history is history
    assert not (tmp_path / "cache" / "scroll").exists()


def test_coding_arms_request_the_coding_toolset_and_scroll_context_engine():
    assert _enabled_toolsets("stock", True) == ["coding"]
    assert _enabled_toolsets("scroll", True) == ["coding", "context_engine"]
    assert _enabled_toolsets("stock", False) == []
    assert _enabled_toolsets("scroll", False) == ["context_engine"]
    with pytest.raises(LiveRunError, match="unknown evaluation arm"):
        _enabled_toolsets("other", True)


def test_tracked_dirty_source_checkout_is_rejected(tmp_path):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True, text=True)

    git("init")
    git("config", "user.email", "eval@example.invalid")
    git("config", "user.name", "Scroll evaluation")
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("committed change\n", encoding="utf-8")
    git("add", "tracked.txt")
    git("commit", "-m", "fixture")
    _require_clean_git_checkout(tmp_path, "fixture")
    tracked.write_text("dirty\n", encoding="utf-8")
    with pytest.raises(LiveRunError, match="tracked changes"):
        _require_clean_git_checkout(tmp_path, "fixture")
    tracked.write_text("clean\n", encoding="utf-8")
    git("add", "tracked.txt")
    git("commit", "-m", "clean fixture")
    shadow = tmp_path / "scroll_eval"
    shadow.mkdir()
    (shadow / "__init__.py").write_text("", encoding="utf-8")
    with pytest.raises(LiveRunError, match="untracked files"):
        _require_clean_git_checkout(tmp_path, "fixture", allow_untracked=False)
