"""Live-evaluation loaders keep benchmark gold outside the agent probe."""

import base64
import json
import os
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from evals.scroll.coding_live import _sandboxed_worker_command
from evals.scroll.hermes_live import EvaluationItem, LiveRunError, _auxiliary_usage, _build_live_agent, _configure_coding_workspace, _enabled_toolsets, _judge_item, _lease_chatgpt_codex_access_token, _prepare_coding_scenario, _require_clean_git_checkout, _resumable_worker_result, _secure_directory, _worker_config, _worker_result_payload, _write_private_json, agent_prompt_sha256, load_beam_items, load_longmemeval_items
from toolsets import resolve_toolset


def _jwt_with_exp(exp):
    encode = lambda value: base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    return f"{encode({'alg': 'none'})}.{encode({'exp': exp})}.signature"


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


def test_resume_rejects_stale_or_mismatched_worker_results(tmp_path):
    result = tmp_path / "result.json"
    provenance = {"manifest_sha256": "manifest", "implementation_commit": "commit", "arm": "stock", "identifier": "item", "model": "model", "history_sha256": "history", "probe_sha256": "probe"}
    result.write_text(json.dumps({"answer": "done", "usage": {"input_tokens": 1, "output_tokens": 2, "cache_read_tokens": 3}, "provenance": provenance}), encoding="utf-8")

    assert _resumable_worker_result(result, provenance)["answer"] == "done"
    assert _resumable_worker_result(result, {**provenance, "implementation_commit": "stale"}) is None
    assert _resumable_worker_result(result, {**provenance, "identifier": "other"}) is None
    result.write_text(json.dumps({"answer": "done", "usage": {"input_tokens": 1, "output_tokens": 2}}), encoding="utf-8")
    assert _resumable_worker_result(result, provenance) is None


def test_coding_worker_result_payload_needs_no_resume_provenance():
    result = _worker_result_payload("done", 1, 2, 3, 0.5)

    assert result == {"answer": "done", "usage": {"input_tokens": 1, "output_tokens": 2, "cache_read_tokens": 3}, "scenario_latency_seconds": 0.5}


def test_live_worker_counts_auxiliary_compression_usage():
    class Connection:
        route = "openai-codex"

        def execute(self, _query, _params):
            return self

        def fetchall(self):
            return [(12, 3, 4, "gpt-5.6-luna", self.route)]

    class Database:
        @contextmanager
        def _read_ctx(self):
            yield Connection()

    assert _auxiliary_usage(Database(), "session", "gpt-5.6-luna") == (12, 3, 4)
    Connection.route = ""
    assert _auxiliary_usage(Database(), "session", "gpt-5.6-luna") == (12, 3, 4)
    Connection.route = "other-provider"
    with pytest.raises(LiveRunError, match="auxiliary"):
        _auxiliary_usage(Database(), "session", "gpt-5.6-luna")
    with pytest.raises(LiveRunError, match="auxiliary"):
        _auxiliary_usage(object(), "session", "gpt-5.6-luna")


def test_live_agent_uses_a_parent_leased_chatgpt_codex_token_without_fallback():
    captured = _build_live_agent(lambda **kwargs: kwargs, {"api_key": "leased-token", "model": "gpt-5.6-luna", "max_iterations": 8, "max_output_tokens": 4096}, "session", object(), ["coding"])

    assert captured["provider"] == "openai-codex"
    assert captured["api_key"] == "leased-token"
    assert captured["base_url"] == "https://chatgpt.com/backend-api/codex"
    assert captured["api_mode"] == "codex_responses"
    assert captured["fallback_model"] == []
    assert "request_overrides" not in captured


def test_parent_leases_worker_access_tokens_with_refresh_headroom(tmp_path):
    calls = []

    def resolver(**kwargs):
        calls.append(kwargs)
        return {"source": "hermes-auth-store", "api_key": "leased-token"}

    assert _lease_chatgpt_codex_access_token(tmp_path, resolver) == "leased-token"
    assert calls == [{"refresh_if_expiring": True, "refresh_skew_seconds": 1_260}]


def test_parent_leases_worker_access_tokens_from_the_credential_pool(tmp_path):
    with patch("evals.scroll.hermes_live.time.time", return_value=1_000):
        assert _lease_chatgpt_codex_access_token(tmp_path, lambda **_kwargs: {"source": "credential_pool", "api_key": _jwt_with_exp(2_261)}) == _jwt_with_exp(2_261)


def test_parent_rejects_expiring_credential_pool_lease(tmp_path):
    with patch("evals.scroll.hermes_live.time.time", return_value=1_000), pytest.raises(LiveRunError, match="verifiable"):
        _lease_chatgpt_codex_access_token(tmp_path, lambda **_kwargs: {"source": "credential_pool", "api_key": _jwt_with_exp(2_260)})


def test_parent_rejects_unverifiable_credential_pool_lease(tmp_path):
    with pytest.raises(LiveRunError, match="verifiable"):
        _lease_chatgpt_codex_access_token(tmp_path, lambda **_kwargs: {"source": "credential_pool", "api_key": "opaque-token"})


def test_parent_rejects_non_store_worker_access_token_sources(tmp_path):
    with pytest.raises(LiveRunError, match="parent-managed"):
        _lease_chatgpt_codex_access_token(tmp_path, lambda **_kwargs: {"source": "worker-supplied", "api_key": "token"})


def test_private_worker_input_has_owner_only_modes(tmp_path):
    runtime_root = tmp_path / "runtime"
    job_root = runtime_root / "jobs" / "job"
    _secure_directory(runtime_root)
    _secure_directory(runtime_root / "jobs")
    _secure_directory(job_root)
    _write_private_json(job_root / "job.json", {"api_key": "leased-token"})

    assert stat.S_IMODE(runtime_root.stat().st_mode) == 0o700
    assert stat.S_IMODE(job_root.stat().st_mode) == 0o700
    assert stat.S_IMODE((job_root / "job.json").stat().st_mode) == 0o600


def test_live_agent_build_uses_the_lease_without_auth_store_resolution():
    from run_agent import AIAgent

    job = {"api_key": "leased-token", "model": "gpt-5.6-luna", "max_iterations": 8, "max_output_tokens": 4096}
    with patch("run_agent.OpenAI", return_value=MagicMock()) as mock_openai, patch("agent.auxiliary_client.resolve_provider_client", side_effect=AssertionError("auth store should not run")):
        agent = _build_live_agent(AIAgent, job, "session", MagicMock(), [])
    try:
        assert mock_openai.call_args.kwargs["api_key"] == "leased-token"
        assert mock_openai.call_args.kwargs["base_url"] == "https://chatgpt.com/backend-api/codex"
    finally:
        agent.close()


def test_worker_config_pins_compression_and_disables_smart_approval():
    config = _worker_config({"arm": "scroll", "model": "gpt-5.6-luna", "context_window": 80000, "max_output_tokens": 4096, "context_total_ceiling_seconds": 1500, "auxiliary_compression_timeout_seconds": 400})

    assert 'mode: "off"' in config
    assert "provider: openai-codex" in config
    assert "api_mode: codex_responses" in config
    assert "context_total_ceiling_seconds: 1500" in config
    assert "timeout: 400" in config


@pytest.mark.parametrize("usage", [{}, {"input_tokens": 1, "output_tokens": 1}, {"input_tokens": 0, "output_tokens": 1, "cache_read_tokens": 0}, {"input_tokens": 1, "output_tokens": 0, "cache_read_tokens": 0}])
def test_memory_judge_rejects_incomplete_or_nonpositive_usage(monkeypatch, tmp_path, usage):
    item = EvaluationItem("longmemeval/case-1", "longmemeval", "single-session-user", "Which?", (), {"answer": "private"})
    captured = {}

    def run(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps({"score": 1, "usage": usage}))

    monkeypatch.setenv("SCROLL_EVAL_TEST_SECRET", "not-forwarded")
    monkeypatch.setattr("evals.scroll.hermes_live.subprocess.run", run)
    manifest = {"judge_model": "gpt-5.6-luna", "max_output_tokens": 32}

    with pytest.raises(LiveRunError, match="usage"):
        _judge_item(item, "answer", manifest, tmp_path / "python", tmp_path, "leased-token")
    assert captured["env"]["HERMES_HOME"] != str(tmp_path / "credentials")
    assert "SCROLL_EVAL_TEST_SECRET" not in captured["env"]
    assert str(Path.cwd()) in captured["env"]["PYTHONPATH"]


def test_coding_workspace_is_registered_for_the_worker_task(tmp_path, monkeypatch):
    registrations = []

    _configure_coding_workspace(tmp_path, "worker-session", lambda task_id, values: registrations.append((task_id, values)))

    assert os.environ["TERMINAL_CWD"] == str(tmp_path)
    assert registrations == [("worker-session", {"cwd": str(tmp_path)})]


def test_coding_worker_command_makes_only_its_job_tree_writable(tmp_path, monkeypatch):
    job_root = tmp_path / "job"
    workspace = job_root / "workspace"
    job_path = job_root / "job.json"
    workspace.mkdir(parents=True)
    monkeypatch.setattr("evals.scroll.coding_live.shutil.which", lambda name: "/usr/bin/bwrap" if name == "bwrap" else None)
    monkeypatch.setenv("SCROLL_EVAL_TEST_SECRET", "not-forwarded")

    command, environment = _sandboxed_worker_command(job_root, job_path, workspace)

    assert ["--ro-bind", "/", "/"] not in [command[index:index + 3] for index in range(len(command) - 2)]
    assert ["--tmpfs", "/home"] in [command[index:index + 2] for index in range(len(command) - 1)]
    resolver_path = str(Path("/etc/resolv.conf").resolve())
    assert ["--ro-bind", resolver_path, resolver_path] in [command[index:index + 3] for index in range(len(command) - 2)]
    assert ["--bind", str(job_root.resolve()), "/work"] in [command[index:index + 3] for index in range(len(command) - 2)]
    assert ["--chdir", "/work/workspace"] in [command[index:index + 2] for index in range(len(command) - 1)]
    assert command[-4:] == ["-m", "evals.scroll.hermes_live", "--worker", "/work/job.json"]
    assert set(environment) == {"HOME", "LANG", "LC_ALL", "PATH", "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE", "PYTHONPATH"}
    assert environment["HOME"] == "/tmp"
    assert "SCROLL_EVAL_TEST_SECRET" not in environment
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert str(Path.cwd()) in environment["PYTHONPATH"]


def test_coding_worker_command_requires_bubblewrap(tmp_path, monkeypatch):
    monkeypatch.setattr("evals.scroll.coding_live.shutil.which", lambda _name: None)

    with pytest.raises(LiveRunError, match="bubblewrap"):
        _sandboxed_worker_command(tmp_path, tmp_path / "job.json", tmp_path)


def test_coding_worker_command_resolves_documented_relative_runtime_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    job_root = Path(".scroll-runtime/live-coding/jobs/task")
    workspace = job_root / "workspace"
    job_path = job_root / "job.json"
    workspace.mkdir(parents=True)
    monkeypatch.setattr("evals.scroll.coding_live.shutil.which", lambda _name: "/usr/bin/bwrap")

    command, _environment = _sandboxed_worker_command(job_root, job_path, workspace)

    assert ["--bind", str(job_root.resolve()), "/work"] in [command[index:index + 3] for index in range(len(command) - 2)]
    assert command[-1] == "/work/job.json"


def test_coding_worker_sandbox_blocks_checkout_writes(tmp_path):
    job_root = tmp_path / "job"
    workspace = job_root / "workspace"
    job_path = job_root / "job.json"
    workspace.mkdir(parents=True)
    command, environment = _sandboxed_worker_command(job_root, job_path, workspace)
    environment["SCROLL_EVAL_CHECKOUT_PATH"] = str(Path(__file__).resolve().parents[2] / "PLAN.md")
    program = (
        "from pathlib import Path; import os, socket; "
        "Path('allowed').write_text('ok'); "
        "checkout = Path(os.environ['SCROLL_EVAL_CHECKOUT_PATH']); "
        "\nif os.access(checkout, os.W_OK):\n raise RuntimeError('sandbox allowed a checkout write')"
        "\nif Path('/home/codex/.hermes/auth.json').exists():\n raise RuntimeError('sandbox exposed caller auth')"
        "\nif not socket.getaddrinfo('chatgpt.com', 443):\n raise RuntimeError('sandbox DNS failed')"
    )

    subprocess.run([*command[:-4], "-c", program], check=True, capture_output=True, text=True, env=environment)

    assert (workspace / "allowed").read_text(encoding="utf-8") == "ok"


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


def test_coding_arms_expose_only_local_editing_tools_and_scroll_context_engine():
    assert _enabled_toolsets("stock", True) == ["terminal", "file"]
    assert _enabled_toolsets("scroll", True) == ["terminal", "file", "context_engine"]
    assert _enabled_toolsets("stock", False) == []
    assert _enabled_toolsets("scroll", False) == ["context_engine"]
    coding_tools = set().union(*(resolve_toolset(toolset, include_registry=False) for toolset in _enabled_toolsets("stock", True)))
    assert coding_tools == {"terminal", "process", "read_file", "write_file", "patch", "search_files"}
    assert not coding_tools & {"delegate_task", "vision_analyze", "browser_vision", "browser_navigate"}
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
