"""Checkpoint contracts for the private BEAM-10M evidence runner."""

import json
from types import SimpleNamespace

import pytest

from plugins.context_engine.scroll.evidence import run_qwen_flash_beam10m as runner
from plugins.context_engine.scroll.evidence import run_codex_beam10m as codex_runner


def test_codex_runner_override_preserves_explicit_manifest_lineage():
    experiment = {"runner_sha256": "a" * 64}

    assert codex_runner._runner_lineage(experiment, "b" * 64, "a" * 64) == ("a" * 64, True)
    with pytest.raises(codex_runner.live.LiveRunError, match="does not match"):
        codex_runner._runner_lineage(experiment, "b" * 64, None)


def _boundary(plan="plan-1"):
    return {"plan": plan, "input_history_sha256": "a" * 64, "output_history_sha256": "b" * 64, "summary_rows": 1, "compression_count_after": 1, "usage": {"input_tokens": 1, "output_tokens": 2, "cache_read_tokens": 3}}


def test_seed_checkpoint_resumes_only_an_ordered_plan_prefix(tmp_path):
    plans = ["plan-1", "plan-2"]
    provenance = {"experiment_manifest_sha256": "manifest", "arm": "A", "conversation": "1"}
    job = {"result_provenance": provenance}
    payload = runner._seed_payload(job, [{"_compressed_summary": True, "content": "summary"}], 3, ["plan-1"], [_boundary()], {"input_tokens": 1, "output_tokens": 2, "cache_read_tokens": 3})
    checkpoint = tmp_path / "checkpoint.json"
    runner.live._write_private_json(checkpoint, payload)

    assert runner._resume_seed_checkpoint(checkpoint, provenance, plans) == payload
    assert runner._resume_seed(checkpoint, provenance, plans) is None


def test_plan_limit_excludes_later_beam_sessions():
    chat = [{"plan-1": [{"batch_number": 1, "turns": [[{"role": "user", "content": "first"}]]}]}, {"plan-2": [{"batch_number": 1, "turns": [[{"role": "user", "content": "second"}]]}]}]

    sessions = list(runner._session_messages(chat, 1))

    assert [session for session, _ in sessions] == ["plan-1"]
    assert sessions[0][1][0]["content"].endswith("first")


def test_plan_order_must_be_chronological():
    chat = [{"plan-2": [{"batch_number": 1, "turns": [[{"role": "user", "content": "second"}]]}]}, {"plan-1": [{"batch_number": 1, "turns": [[{"role": "user", "content": "first"}]]}]}]

    try:
        list(runner._session_messages(chat))
    except runner.live.LiveRunError as exc:
        assert str(exc) == "BEAM 10M plans are not in chronological order"
    else:
        raise AssertionError("expected chronological-order rejection")


def test_boundary_summary_requires_a_committed_hermes_summary():
    class Compressor:
        tail_token_budget = 4096
        compression_count = 0
        _last_compression_made_progress = False
        _last_summary_fallback_used = False
        _last_compress_aborted = False

        @staticmethod
        def has_content_to_compress(history):
            return bool(history)

    compressor = Compressor()

    class Agent:
        context_compressor = compressor
        tools = []
        _last_compression_attempt_in_place = None

        @staticmethod
        def _build_system_prompt(prompt):
            return prompt

        def _compress_context(self, history, _prompt, **_kwargs):
            assert compressor.tail_token_budget == runner._A_FORCED_TAIL_TOKEN_BUDGET
            compressor.compression_count += 1
            compressor._last_compression_made_progress = True
            self._last_compression_attempt_in_place = True
            return [{"role": "user", "content": "summary", "_compressed_summary": True}], ""

    compacted, count = runner._boundary_summary(Agent(), [{"role": "user", "content": "history"}], task_id="test")

    assert count == 1
    assert compacted[0]["_compressed_summary"] is True
    assert compressor.tail_token_budget == 4096


def test_conversation_partition_keeps_seed_and_arms_together(monkeypatch, tmp_path):
    events = []
    seed = (tmp_path / "seed.json", {"metadata": {}}, {"seed": "provenance"})
    items = [SimpleNamespace(identifier="beam/10M/1/abstention-0")]

    def prepare(conversation, **_kwargs):
        events.append(("seed", conversation))
        return seed

    def run_item(item, arm, **kwargs):
        events.append(("probe", arm, item.identifier, set(kwargs["seeds"])))
        return {"task_id": item.identifier, "provenance": {"arm": arm}}

    monkeypatch.setattr(runner, "_prepare_seed", prepare)
    monkeypatch.setattr(runner, "_run_item", run_item)

    conversation, returned_seed, rows = runner._run_conversation_partition("1", items, ("A", "C"), experiment={}, experiment_digest="digest", chats_root=tmp_path, scroll_source=tmp_path, source_python=tmp_path, runtime_root=tmp_path, credential_home=tmp_path, plan_limit=10, manifest_runner_sha256="m" * 64, execution_runner_sha256="e" * 64, runner_override=True, execution_qwen_runner_sha256="q" * 64, judge_program_sha256="p" * 64, judge_timeout_seconds=1800, reuse_execution_runner_sha256=None, probe_workers=1)

    assert conversation == "1"
    assert returned_seed == seed
    assert rows == [{"task_id": "beam/10M/1/abstention-0", "provenance": {"arm": "A"}}, {"task_id": "beam/10M/1/abstention-0", "provenance": {"arm": "C"}}]
    assert events == [("seed", "1"), ("probe", "A", "beam/10M/1/abstention-0", {"1"}), ("probe", "C", "beam/10M/1/abstention-0", {"1"})]


def test_ac_only_selects_only_forced_compression_and_required_scroll():
    assert runner._selected_arms(ac_only=True, include_raw_history_control=False) == ("A", "C")


def test_ac_only_rejects_the_raw_history_control():
    try:
        runner._selected_arms(ac_only=True, include_raw_history_control=True)
    except runner.live.LiveRunError as exc:
        assert str(exc) == "--ac-only cannot be combined with --include-raw-history-control"
    else:
        raise AssertionError("expected incompatible arm selection to fail")


def test_explicit_conversation_selection_preserves_manifest_order():
    assert runner._select_conversations(["1", "2", "3"], ["3", "2"]) == ["2", "3"]

    with pytest.raises(runner.live.LiveRunError, match="conversation selection"):
        runner._select_conversations(["1", "2", "3"], ["2", "2"])


def test_seed_namespace_and_provenance_pin_the_executing_runner(tmp_path):
    experiment = {"implementation_commit": "commit", "runner_sha256": "m" * 64}
    chat_path = tmp_path / "chat.json"
    chat_path.write_text("[]", encoding="utf-8")

    old_root = runner._seed_root(tmp_path, experiment_digest="d" * 64, execution_runner_sha256="o" * 64, plan_label="10", conversation="2")
    new_root = runner._seed_root(tmp_path, experiment_digest="d" * 64, execution_runner_sha256="n" * 64, plan_label="10", conversation="2")
    provenance = runner._seed_provenance("2", experiment=experiment, experiment_digest="d" * 64, chat_path=chat_path, plan_label="10", execution_runner_sha256="n" * 64, runner_override=True)

    assert old_root != new_root
    assert provenance["manifest_runner_sha256"] == "m" * 64
    assert provenance["execution_runner_sha256"] == "n" * 64
    assert provenance["runner_override"] is True


def test_seed_phase_drains_the_queue_before_failing(monkeypatch, tmp_path):
    events = []

    def prepare(conversation, **_kwargs):
        events.append(conversation)
        if conversation == "2":
            raise runner.live.LiveRunError("expected")
        return tmp_path / f"{conversation}.json", {"metadata": {}}, {}

    monkeypatch.setattr(runner, "_prepare_seed", prepare)

    with pytest.raises(runner.live.LiveRunError, match="seeds failed after draining"):
        runner._prepare_seed_phase(["1", "2", "3"], ("A", "C"), experiment={}, experiment_digest="digest", chats_root=tmp_path, runtime_root=tmp_path, credential_home=tmp_path, plan_limit=10, execution_runner_sha256="e" * 64, runner_override=True, seed_workers=1)

    assert events == ["1", "2", "3"]


def test_runner_override_requires_the_exact_executing_sha():
    assert runner._runner_override_is_valid("m" * 64, "m" * 64, None) is False
    assert runner._runner_override_is_valid("m" * 64, "e" * 64, "e" * 64) is True

    try:
        runner._runner_override_is_valid("m" * 64, "e" * 64, None)
    except runner.live.LiveRunError as exc:
        assert "does not match its manifest" in str(exc)
    else:
        raise AssertionError("expected missing runner SHA acceptance to fail")

    try:
        runner._runner_override_is_valid("m" * 64, "e" * 64, "f" * 64)
    except runner.live.LiveRunError as exc:
        assert str(exc) == "--accept-runner-sha must equal the executing runner SHA"
    else:
        raise AssertionError("expected incorrect runner SHA acceptance to fail")


def test_worker_rejects_a_job_for_a_different_runner_sha():
    try:
        runner._validate_execution_runner_sha({"execution_runner_sha256": "0" * 64})
    except runner.live.LiveRunError as exc:
        assert str(exc) == "BEAM 10M worker runner SHA does not match its job"
    else:
        raise AssertionError("expected runner SHA mismatch to fail")


def test_legacy_row_reuse_requires_a_linked_result(tmp_path):
    provenance = {"experiment_manifest_sha256": "manifest", "arm": "C", "execution_runner_sha256": "e" * 64}
    usage = {"input_tokens": 1, "output_tokens": 2, "cache_read_tokens": 3}
    result_path = tmp_path / "result.json"
    row_path = tmp_path / "row.json"
    runner.live._write_private_json(result_path, {"answer": "answer", "usage": usage, "scroll_repl_calls": 1, "seed_metadata": None, "provenance": provenance})
    row = {"task_id": "item", "score": 1.0, "answer_sha256": runner.hashlib.sha256(b"answer").hexdigest(), "usage": usage, "judge_usage": usage, "scroll_repl_calls": 1, "seed_metadata": None, "provenance": provenance}
    runner.live._write_private_json(row_path, row)

    assert runner._legacy_row_is_valid(row_path, result_path, provenance, "C") == row

    row["answer_sha256"] = "0" * 64
    runner.live._write_private_json(row_path, row)
    assert runner._legacy_row_is_valid(row_path, result_path, provenance, "C") is None


def test_reuse_execution_requires_an_exact_prior_execution_record(tmp_path):
    old_runner_sha = "o" * 64
    record_path = tmp_path / "executions" / "old" / "execution.json"
    record_path.parent.mkdir(parents=True)
    runner.live._write_private_json(record_path, {"experiment_manifest_sha256": "m" * 64, "manifest_runner_sha256": "r" * 64, "execution_runner_sha256": old_runner_sha, "runner_override": True, "arms": ["A", "C"], "conversations": ["1"], "plan_limit": 10})

    runner._validate_reuse_execution(tmp_path, experiment_digest="m" * 64, manifest_runner_sha256="r" * 64, execution_runner_sha256="n" * 64, reuse_execution_runner_sha256=old_runner_sha, arms=("A", "C"), conversations=["1"], plan_limit=10)

    with pytest.raises(runner.live.LiveRunError, match="not a matching"):
        runner._validate_reuse_execution(tmp_path, experiment_digest="m" * 64, manifest_runner_sha256="r" * 64, execution_runner_sha256="n" * 64, reuse_execution_runner_sha256=old_runner_sha, arms=("A", "C"), conversations=["1"], plan_limit=9)


def test_partition_drains_serial_jobs_after_one_failure(monkeypatch, tmp_path):
    seed = (tmp_path / "seed.json", {"metadata": {}}, {"seed": "provenance"})
    items = [SimpleNamespace(identifier="beam/10M/1/abstention-0")]
    events = []

    monkeypatch.setattr(runner, "_prepare_seed", lambda *_args, **_kwargs: seed)

    def run_item(item, arm, **_kwargs):
        events.append(arm)
        if arm == "A":
            raise runner.live.LiveRunError("expected")
        return {"task_id": item.identifier, "provenance": {"arm": arm}}

    monkeypatch.setattr(runner, "_run_item", run_item)

    with pytest.raises(runner.live.LiveRunError, match="A:beam/10M/1/abstention-0"):
        runner._run_conversation_partition("1", items, ("A", "C"), experiment={}, experiment_digest="digest", chats_root=tmp_path, scroll_source=tmp_path, source_python=tmp_path, runtime_root=tmp_path, credential_home=tmp_path, plan_limit=10, manifest_runner_sha256="m" * 64, execution_runner_sha256="e" * 64, runner_override=True, execution_qwen_runner_sha256="q" * 64, judge_program_sha256="p" * 64, judge_timeout_seconds=1800, reuse_execution_runner_sha256=None, probe_workers=1)

    assert events == ["A", "C"]


def test_partition_drains_parallel_jobs_after_one_failure(monkeypatch, tmp_path):
    seed = (tmp_path / "seed.json", {"metadata": {}}, {"seed": "provenance"})
    items = [SimpleNamespace(identifier="beam/10M/1/abstention-0")]
    events = []

    monkeypatch.setattr(runner, "_prepare_seed", lambda *_args, **_kwargs: seed)

    def run_item(item, arm, **_kwargs):
        events.append(arm)
        if arm == "A":
            raise runner.live.LiveRunError("expected")
        return {"task_id": item.identifier, "provenance": {"arm": arm}}

    monkeypatch.setattr(runner, "_run_item", run_item)

    with pytest.raises(runner.live.LiveRunError, match="A:beam/10M/1/abstention-0"):
        runner._run_conversation_partition("1", items, ("A", "C"), experiment={}, experiment_digest="digest", chats_root=tmp_path, scroll_source=tmp_path, source_python=tmp_path, runtime_root=tmp_path, credential_home=tmp_path, plan_limit=10, manifest_runner_sha256="m" * 64, execution_runner_sha256="e" * 64, runner_override=True, execution_qwen_runner_sha256="q" * 64, judge_program_sha256="p" * 64, judge_timeout_seconds=1800, reuse_execution_runner_sha256=None, probe_workers=2)

    assert sorted(events) == ["A", "C"]


def test_judge_timeout_has_a_bounded_operational_range():
    runner._validate_judge_timeout_seconds(600)
    runner._validate_judge_timeout_seconds(1800)

    with pytest.raises(runner.live.LiveRunError, match="judge timeout"):
        runner._validate_judge_timeout_seconds(599)


def test_status_exposes_only_durable_progress_counts(tmp_path):
    provenance = {"experiment_manifest_sha256": "manifest", "arm": "A", "conversation": "1", "execution_plan_limit": "1"}
    seed_root = tmp_path / "seeds" / "seed"
    job_root = tmp_path / "jobs" / "job"
    seed_root.mkdir(parents=True)
    job_root.mkdir(parents=True)
    runner.live._write_private_json(seed_root / "checkpoint.json", runner._seed_payload({"result_provenance": provenance}, [{"_compressed_summary": True, "content": "summary"}], 3, ["plan-1"], [_boundary()], {"input_tokens": 1, "output_tokens": 2, "cache_read_tokens": 3}))
    runner.live._write_private_json(job_root / "result.json", {"answer": "secret answer", "provenance": provenance})

    report = runner.status(tmp_path)

    assert report["seeds"] == [{"conversation": "1", "completed_plans": 1, "finalized": False}]
    assert report["jobs_by_plan_limit"]["1"]["A"] == {"jobs": 1, "answer_checkpoints": 1, "scored_rows": 0, "queued_or_running": 0, "awaiting_score": 1}
    assert "secret answer" not in json.dumps(report)


def test_status_ignores_empty_stale_job_directories(tmp_path):
    (tmp_path / "jobs" / "stale").mkdir(parents=True)

    report = runner.status(tmp_path)

    assert report["jobs_by_plan_limit"] == {}


def test_status_counts_a_durable_queued_probe_without_a_credential_file(tmp_path):
    provenance = {"arm": "C", "execution_plan_limit": "10"}
    state_path = tmp_path / "jobs" / "queued" / "state.json"
    state_path.parent.mkdir(parents=True)
    runner.live._write_private_json(state_path, {"provenance": provenance, "state": "queued"})

    report = runner.status(tmp_path)

    assert report["jobs_by_plan_limit"]["10"]["C"] == {"jobs": 1, "answer_checkpoints": 0, "scored_rows": 0, "queued_or_running": 1, "awaiting_score": 0}
