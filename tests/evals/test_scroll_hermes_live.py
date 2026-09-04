"""Live-evaluation loaders keep benchmark gold outside the agent probe."""

import json

from evals.scroll.hermes_live import agent_prompt_sha256, load_beam_items, load_longmemeval_items


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
