"""Focused contracts for the subprocess-isolated Hermes LOCA adapter."""

import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest

from evals.scroll import loca_live
from plugins.context_engine.scroll.evidence import run_hermes_loca as adapter


def _entry(seed=42):
    return {
        "name": "ABTestingS2LEnv",
        "env_class": "fake_env.FakeEnv",
        "env_params": {"seed": seed},
        "mcp_servers": {},
    }


def _task(entry):
    return loca_live.LocaTask(
        entry["name"], entry["env_class"], entry["env_params"]["seed"], "128k",
        adapter._sha256_json(entry), adapter._sha256_json(entry["mcp_servers"]),
    )


def _worker_spec(tmp_path, entry, *, job_name="job"):
    source = tmp_path / "loca-source"
    source.mkdir(exist_ok=True)
    return {
        "schema_version": 1,
        "job_root": str(tmp_path / job_name),
        "task_root": str(tmp_path / "task"),
        "loca_source": str(source),
        "loca_python": sys.executable,
        "worker_path": "/usr/bin",
        "entry": entry,
        "task_configuration_sha256": adapter._sha256_json(entry),
    }, source


def test_raw_entries_are_bound_to_the_loca_task_configuration_hash(tmp_path):
    entry = _entry()
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"configurations": [entry]}), encoding="utf-8")

    loaded = adapter.load_raw_loca_entries(config, [_task(entry)])

    assert loaded[("ABTestingS2LEnv", 42)] == entry

    changed = _entry()
    changed["env_params"]["unexpected_change"] = "tampered"
    config.write_text(json.dumps({"configurations": [changed]}), encoding="utf-8")
    with pytest.raises(adapter.LocaAdapterError, match="hash does not match"):
        adapter.load_raw_loca_entries(config, [_task(entry)])


def test_worker_environment_is_private_per_job_and_has_no_parent_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("UNRELATED_PARENT_SECRET", "not-for-workers")
    first, _ = _worker_spec(tmp_path, _entry(), job_name="first")
    second, _ = _worker_spec(tmp_path, _entry(), job_name="second")

    first_environment = adapter._worker_environment(first)
    second_environment = adapter._worker_environment(second)

    assert set(first_environment) == {"HOME", "HERMES_HOME", "PATH", "PYTHONPATH", "TMPDIR", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED"}
    assert first_environment["HERMES_HOME"] != second_environment["HERMES_HOME"]
    assert first_environment["PYTHONPATH"].split(":")[0] == first["loca_source"]
    assert "UNRELATED_PARENT_SECRET" not in first_environment


def test_worker_environment_preserves_the_selected_virtualenv_interpreter(tmp_path):
    spec, _ = _worker_spec(tmp_path, _entry())
    interpreter = tmp_path / "virtualenv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to(sys.executable)
    spec["loca_python"] = str(interpreter)

    environment = adapter._worker_environment(spec)

    assert environment["PATH"].split(":")[0] == str(interpreter.parent)


def test_worker_launcher_rejects_an_unavailable_python_before_spawn(tmp_path):
    spec, _source = _worker_spec(tmp_path, _entry())
    spec["loca_python"] = str(tmp_path / "missing-python")

    with pytest.raises(adapter.LocaAdapterError, match="no usable Python interpreter"):
        adapter._invoke_worker("materialize", spec, timeout_seconds=30)


def test_python_executor_runtime_requires_uv(tmp_path, monkeypatch):
    with pytest.raises(adapter.LocaAdapterError, match="uv"):
        monkeypatch.setattr(adapter, "_resolve_executable", lambda *_args, **_kwargs: (_ for _ in ()).throw(adapter.LocaAdapterError("LOCA MCP dependency 'uv' is unavailable on the worker PATH")))
        adapter._require_python_executor_runtime(worker_path="/missing", loca_python=tmp_path / "python")


def test_hermes_worker_uses_the_locked_hermes_interpreter(tmp_path, monkeypatch):
    spec, _ = _worker_spec(tmp_path, _entry())
    hermes_python = tmp_path / "hermes" / "bin" / "python"
    hermes_python.parent.mkdir(parents=True)
    hermes_python.symlink_to(sys.executable)
    spec["hermes_python"] = str(hermes_python)
    commands = []

    class Process:
        returncode = 0

        def communicate(self, timeout):
            return "", ""

    monkeypatch.setattr(adapter.subprocess, "Popen", lambda command, **_kwargs: commands.append(command) or Process())
    monkeypatch.setattr(adapter, "_read_json", lambda *_args: {})

    adapter._invoke_worker("materialize", spec, timeout_seconds=30)
    adapter._invoke_worker("hermes", spec, timeout_seconds=30)

    assert commands[0][0] == str(Path(sys.executable).absolute())
    assert commands[1][0] == str(hermes_python.absolute())


def test_openai_codex_honors_the_requested_reasoning_configuration():
    kwargs = adapter._model_kwargs({"model": {"provider": "openai-codex", "api_key": "token", "name": "gpt-5.3-codex", "reasoning_config": {"enabled": True, "effort": "high"}}})

    assert kwargs["reasoning_config"] == {"enabled": True, "effort": "high"}
    assert kwargs["api_mode"] == "codex_responses"


def test_cli_accepts_luna_max_and_a_single_arm(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_hermes_loca.py", "--loca-source", "/tmp/loca", "--model", "gpt-5.6-luna", "--reasoning-effort", "max", "--trial", "trial-one", "--arm", "stock"])

    args = adapter._parse_args()

    assert args.reasoning_effort == "max"
    assert args.trial == "trial-one"
    assert args.arms == ["stock"]


def test_openai_codex_disables_reasoning_when_the_configuration_is_omitted():
    kwargs = adapter._model_kwargs({"model": {"provider": "openai-codex", "api_key": "token", "name": "gpt-5.3-codex"}})

    assert kwargs["reasoning_config"] == {"enabled": False}


def test_worker_config_disables_unrelated_title_generation():
    config = json.loads(adapter._worker_config({}, arm="stock", context_window=128000))

    assert config["auxiliary"]["title_generation"] == {"enabled": False}


def test_system_prompt_binds_the_exact_workspace_and_protocols(tmp_path):
    workspace = tmp_path / "agent_workspace"

    stock = adapter._system_prompt(workspace, arm="stock", has_python_executor=True)
    scroll = adapter._system_prompt(workspace, arm="scroll", has_python_executor=True)
    without_executor = adapter._system_prompt(workspace, arm="stock", has_python_executor=False)

    assert str(workspace) in stock
    assert "scroll_repl" not in stock
    assert "do not substitute a sample" in stock
    assert "Python executor" in stock
    assert "../local_db" in stock
    assert "standard-library sqlite3" in stock
    assert "percentage-scale values" in stock
    assert "Python executor" not in without_executor
    assert "../local_db" not in without_executor
    assert str(workspace) in scroll
    assert "scroll_repl" in scroll


def test_scroll_required_rejects_a_trajectory_without_scroll_repl():
    messages = [{"role": "assistant", "tool_calls": [{"function": {"name": "tool_call"}}]}]

    assert adapter._assert_scroll_required(messages, arm="stock") == 0
    with pytest.raises(adapter.LocaAdapterError, match="without calling scroll_repl"):
        adapter._assert_scroll_required(messages, arm="scroll")
    assert adapter._assert_scroll_required([{"role": "assistant", "tool_calls": [{"function": {"name": "scroll_repl"}}]}], arm="scroll") == 1


def test_hermes_worker_starts_in_the_agent_workspace(tmp_path, monkeypatch):
    task_workspace = tmp_path / "environment"
    agent_workspace = task_workspace / "agent_workspace"
    agent_workspace.mkdir(parents=True)
    job_root = tmp_path / "job"
    job_root.mkdir()
    hermes_home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    changed_directories = []
    prompts = []

    class Database:
        def __init__(self, *_args):
            pass

        def create_session(self, *_args, **_kwargs):
            pass

        def close(self):
            pass

    class Agent:
        valid_tool_names = {"scroll_repl"}

        def __init__(self, **_kwargs):
            pass

        def run_conversation(self, _prompt, *, system_message, **_kwargs):
            prompts.append(system_message)
            return {"final_response": "done", "messages": [{"role": "assistant", "tool_calls": [{"function": {"name": "scroll_repl"}}]}]}

        def close(self):
            pass

    mcp_tool = ModuleType("tools.mcp_tool")
    mcp_tool.register_mcp_servers = lambda _servers: {}
    mcp_tool.get_registered_mcp_server_names = lambda: set()
    mcp_tool.shutdown_mcp_servers = lambda: None
    hermes_state = ModuleType("hermes_state")
    hermes_state.SessionDB = Database
    run_agent = ModuleType("run_agent")
    run_agent.AIAgent = Agent
    monkeypatch.setitem(sys.modules, "tools.mcp_tool", mcp_tool)
    monkeypatch.setitem(sys.modules, "hermes_state", hermes_state)
    monkeypatch.setitem(sys.modules, "run_agent", run_agent)
    monkeypatch.setattr(adapter, "_assert_arm_semantics", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(adapter.os, "chdir", lambda path: changed_directories.append(Path(path)))

    adapter._run_hermes("task", {"arm": "scroll", "context_window": 128000, "job_root": str(job_root), "model": {"provider": "openrouter", "api_key": "token", "name": "model"}, "max_iterations": 12, "max_output_tokens": 100}, task_workspace=task_workspace, mcp_servers={})

    assert changed_directories[0] == agent_workspace
    assert str(agent_workspace) in prompts[0]
    assert "scroll_repl" in prompts[0]


def test_semantic_plan_hash_binds_worker_timeouts(tmp_path):
    args = SimpleNamespace(loca_python=tmp_path / "loca-python", hermes_python=tmp_path / "hermes-python", provider="openai-codex", model="gpt-5.3-codex", context_window=262144, max_iterations=120, max_output_tokens=8192, setup_timeout_seconds=1800, job_timeout_seconds=3000, reasoning_effort="high", service_tier="")

    first = adapter._semantic_plan_sha256(args, config_sha256="a" * 64)
    args.job_timeout_seconds = 3600

    assert adapter._semantic_plan_sha256(args, config_sha256="a" * 64) != first


def test_semantic_plan_hash_binds_trial(tmp_path):
    args = SimpleNamespace(loca_python=tmp_path / "loca-python", hermes_python=tmp_path / "hermes-python", provider="openai-codex", model="gpt-5.6-luna", context_window=262144, max_iterations=120, max_output_tokens=8192, setup_timeout_seconds=1800, job_timeout_seconds=3000, reasoning_effort="medium", service_tier="", trial="one")

    first = adapter._semantic_plan_sha256(args, config_sha256="a" * 64)
    args.trial = "two"

    assert adapter._semantic_plan_sha256(args, config_sha256="a" * 64) != first


def test_arm_semantics_reject_scroll_fallback_before_the_model_turn():
    class ScrollEngine:
        name = "scroll"

    class BuiltinCompressor:
        pass

    scroll_agent = SimpleNamespace(context_compressor=ScrollEngine(), valid_tool_names={"scroll_repl"})
    stock_agent = SimpleNamespace(context_compressor=BuiltinCompressor(), valid_tool_names=set())

    adapter._assert_arm_semantics(scroll_agent, "scroll", scroll_engine_type=ScrollEngine, compressor_type=BuiltinCompressor, scroll_tool_name="scroll_repl")
    adapter._assert_arm_semantics(stock_agent, "stock", scroll_engine_type=ScrollEngine, compressor_type=BuiltinCompressor, scroll_tool_name="scroll_repl")

    with pytest.raises(adapter.LocaAdapterError, match="fell back"):
        adapter._assert_arm_semantics(stock_agent, "scroll", scroll_engine_type=ScrollEngine, compressor_type=BuiltinCompressor, scroll_tool_name="scroll_repl")
    with pytest.raises(adapter.LocaAdapterError, match="leaked"):
        adapter._assert_arm_semantics(SimpleNamespace(context_compressor=BuiltinCompressor(), valid_tool_names={"scroll_repl"}), "stock", scroll_engine_type=ScrollEngine, compressor_type=BuiltinCompressor, scroll_tool_name="scroll_repl")


def test_materializer_runs_in_a_fresh_worker_and_keeps_ground_truth_out_of_execution_state(tmp_path):
    entry = _entry()
    spec, source = _worker_spec(tmp_path, entry)
    (source / "fake_env.py").write_text(
        "import json, os\n"
        "from pathlib import Path\n"
        "class FakeEnv:\n"
        "    def __init__(self, task_dir, **_):\n"
        "        root = Path(task_dir)\n"
        "        (root / 'agent_workspace').mkdir(parents=True)\n"
        "        (root / 'agent_workspace' / 'input.txt').write_text('paired input')\n"
        "        (root / 'local_db').mkdir()\n"
        "        (root / 'local_db' / 'state.txt').write_text('database')\n"
        "        (root / 'groundtruth_workspace').mkdir()\n"
        "        (root / 'groundtruth_workspace' / 'answer.txt').write_text('secret answer')\n"
        "        (root / 'worker-environment.json').write_text(json.dumps({'home': os.environ['HERMES_HOME'], 'path': os.environ['PYTHONPATH']}))\n",
        encoding="utf-8",
    )

    result = adapter._invoke_worker("materialize", spec, timeout_seconds=30)
    snapshot = Path(spec["task_root"]) / result["snapshot_path"]
    execution = snapshot / "execution"

    assert result["execution_sha256"] == adapter._tree_sha256(execution)
    assert (execution / "agent_workspace" / "input.txt").read_text(encoding="utf-8") == "paired input"
    assert not (execution / "groundtruth_workspace").exists()
    assert (snapshot / "verifier" / "groundtruth_workspace" / "answer.txt").read_text(encoding="utf-8") == "secret answer"
    assert json.loads((snapshot / "snapshot-manifest.json").read_text(encoding="utf-8"))["groundtruth_present"] is True
    recorded = json.loads((execution / "worker-environment.json").read_text(encoding="utf-8"))
    assert recorded["home"].endswith("job/hermes-home")
    assert recorded["path"].split(":")[0] == str(source)


def test_structural_preflight_does_not_start_hermes_or_mcp_servers(tmp_path):
    entry = _entry()
    entry["mcp_servers"] = {"claim_done": {"enabled": True, "type": "claim_done", "params": {}}}
    spec, source = _worker_spec(tmp_path, entry)
    (source / "fake_env.py").write_text("class FakeEnv:\n    pass\n", encoding="utf-8")
    config_loader = source / "gem" / "tools" / "mcp_server"
    config_loader.mkdir(parents=True)
    for package in (source / "gem", source / "gem" / "tools", config_loader):
        (package / "__init__.py").write_text("", encoding="utf-8")
    (config_loader / "config_loader.py").write_text(
        "def build_server_config(server_type, params, server_name):\n"
        "    return {server_name: {'command': 'python', 'args': [], 'env': {}}}\n",
        encoding="utf-8",
    )

    result = adapter._invoke_worker("preflight", {**spec, "entries": [entry]}, timeout_seconds=30)

    assert result == {"status": "structural-ready", "hermes_started": False, "mcp_servers_started": False}


def test_google_cloud_mcp_uses_the_pinned_loca_interpreter(tmp_path, monkeypatch):
    entry = _entry()
    entry["mcp_servers"] = {"google_cloud": {"enabled": True, "type": "google_cloud", "params": {}}}
    spec, source = _worker_spec(tmp_path, entry)
    config_loader = source / "gem" / "tools" / "mcp_server"
    script = source / "mcp_convert" / "mcps" / "google_cloud" / "server.py"
    script.parent.mkdir(parents=True)
    script.write_text("", encoding="utf-8")
    for package in (source / "gem", source / "gem" / "tools", config_loader):
        package.mkdir(parents=True, exist_ok=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
    config_loader.mkdir(parents=True, exist_ok=True)
    (config_loader / "config_loader.py").write_text(
        "def build_server_config(server_type, params, server_name):\n"
        "    return {server_name: {'command': 'uv', 'args': ['--directory', r'" + str(source / "mcp_convert") + "', 'run', 'python', r'" + str(script) + "'], 'env': {}}}\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(source))

    translated = adapter.translate_loca_mcp_config(entry, loca_source=source, loca_python=Path(sys.executable), task_workspace=tmp_path / "workspace", worker_path="/usr/bin")

    assert translated["google_cloud"]["command"] == str(Path(sys.executable).absolute())
    assert translated["google_cloud"]["args"] == [str(script)]


def test_terminal_mcp_pins_a_compatible_runtime(tmp_path, monkeypatch):
    entry = _entry()
    entry["mcp_servers"] = {"terminal": {"enabled": True, "type": "terminal", "params": {}}}
    _spec, source = _worker_spec(tmp_path, entry)
    config_loader = source / "gem" / "tools" / "mcp_server"
    for package in (source / "gem", source / "gem" / "tools", config_loader):
        package.mkdir(parents=True, exist_ok=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
    (config_loader / "config_loader.py").write_text(
        "def build_server_config(server_type, params, server_name):\n"
        "    return {server_name: {'command': 'uvx', 'args': ['cli-mcp-server'], 'env': {}}}\n",
        encoding="utf-8",
    )
    for module_name in ("gem.tools.mcp_server.config_loader", "gem.tools.mcp_server", "gem.tools", "gem"):
        monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.syspath_prepend(str(source))
    monkeypatch.setattr(adapter, "_resolve_executable", lambda command, **_kwargs: command)

    translated = adapter.translate_loca_mcp_config(entry, loca_source=source, loca_python=Path(sys.executable), task_workspace=tmp_path / "workspace", worker_path="/usr/bin")

    assert translated["terminal"]["args"] == ["--from", "cli-mcp-server==0.2.5", "--with", "mcp<2", "cli-mcp-server"]


def test_pdf_tools_mcp_pins_a_compatible_runtime(tmp_path, monkeypatch):
    entry = _entry()
    entry["mcp_servers"] = {"pdf_tools": {"enabled": True, "type": "pdf_tools", "params": {}}}
    _spec, source = _worker_spec(tmp_path, entry)
    config_loader = source / "gem" / "tools" / "mcp_server"
    for package in (source / "gem", source / "gem" / "tools", config_loader):
        package.mkdir(parents=True, exist_ok=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
    (config_loader / "config_loader.py").write_text(
        "def build_server_config(server_type, params, server_name):\n"
        "    return {server_name: {'command': 'uvx', 'args': ['pdf-tools-mcp', '--workspace_path', 'workspace'], 'env': {}}}\n",
        encoding="utf-8",
    )
    for module_name in ("gem.tools.mcp_server.config_loader", "gem.tools.mcp_server", "gem.tools", "gem"):
        monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.syspath_prepend(str(source))
    monkeypatch.setattr(adapter, "_resolve_executable", lambda command, **_kwargs: command)

    translated = adapter.translate_loca_mcp_config(entry, loca_source=source, loca_python=Path(sys.executable), task_workspace=tmp_path / "workspace", worker_path="/usr/bin")

    assert translated["pdf_tools"]["args"] == ["--from", "pdf-tools-mcp==0.1.4", "--with", "mcp<2", "pdf-tools-mcp", "--workspace_path", "workspace"]


def test_restore_is_paired_and_ground_truth_is_staged_only_for_verification(tmp_path):
    snapshot = tmp_path / "snapshot"
    execution = snapshot / "execution"
    (execution / "agent_workspace").mkdir(parents=True)
    (execution / "agent_workspace" / "input.txt").write_text("paired input", encoding="utf-8")
    verifier = snapshot / "verifier" / "groundtruth_workspace"
    verifier.mkdir(parents=True)
    (verifier / "answer.txt").write_text("secret answer", encoding="utf-8")
    execution_sha = adapter._tree_sha256(execution)
    adapter._write_json(snapshot / "snapshot-manifest.json", {"schema_version": 2, "execution_sha256": execution_sha, "groundtruth_present": True, "groundtruth_sha256": adapter._tree_sha256(verifier)})
    task_workspace = tmp_path / "job-environment"
    (task_workspace / "groundtruth_workspace").mkdir(parents=True)
    (task_workspace / "groundtruth_workspace" / "old.txt").write_text("generated", encoding="utf-8")

    restored = adapter._restore_execution_state(snapshot, task_workspace)

    assert restored == execution_sha
    assert not (task_workspace / "groundtruth_workspace").exists()
    assert (task_workspace / "agent_workspace" / "input.txt").read_text(encoding="utf-8") == "paired input"
    assert adapter._stage_groundtruth(snapshot, task_workspace) == adapter._tree_sha256(verifier)
    assert (task_workspace / "groundtruth_workspace" / "answer.txt").read_text(encoding="utf-8") == "secret answer"


def test_materializer_preserves_valid_tasks_without_ground_truth(tmp_path):
    entry = _entry()
    spec, source = _worker_spec(tmp_path, entry)
    (source / "fake_env.py").write_text(
        "from pathlib import Path\n"
        "class FakeEnv:\n"
        "    def __init__(self, task_dir, **_):\n"
        "        root = Path(task_dir)\n"
        "        (root / 'agent_workspace').mkdir(parents=True)\n"
        "        (root / 'agent_workspace' / 'input.txt').write_text('paired input')\n",
        encoding="utf-8",
    )

    result = adapter._invoke_worker("materialize", spec, timeout_seconds=30)
    snapshot = Path(spec["task_root"]) / result["snapshot_path"]
    task_workspace = tmp_path / "job-environment"

    restored = adapter._restore_execution_state(snapshot, task_workspace)

    assert restored == result["execution_sha256"]
    assert adapter._stage_groundtruth(snapshot, task_workspace) == adapter._sha256_bytes(b"groundtruth-absent")
    assert not (task_workspace / "groundtruth_workspace").exists()


def test_materializer_rejects_an_environment_without_an_agent_workspace(tmp_path):
    entry = _entry()
    spec, source = _worker_spec(tmp_path, entry)
    (source / "fake_env.py").write_text(
        "from pathlib import Path\n"
        "class FakeEnv:\n"
        "    def __init__(self, task_dir, **_):\n"
        "        Path(task_dir).mkdir(parents=True)\n",
        encoding="utf-8",
    )

    with pytest.raises(adapter.LocaAdapterError, match="did not materialize agent_workspace"):
        adapter._invoke_worker("materialize", spec, timeout_seconds=30)


def test_native_verifier_requires_a_normal_terminal_receipt():
    score, info = adapter._accept_verifier_result(("done", 1.0, True, False, {"native": "passed"}))

    assert score == 1.0
    assert info == {"native": "passed"}

    with pytest.raises(adapter.LocaAdapterError, match="did not terminate"):
        adapter._accept_verifier_result(("done", 0.0, False, False, {}))
    with pytest.raises(adapter.LocaAdapterError, match="invalid score"):
        adapter._accept_verifier_result(("done", 2.0, True, False, {}))


def test_verifier_hash_uses_only_tracked_loca_environment_source(tmp_path):
    source = tmp_path / "loca-source"
    verifier = source / "gem" / "envs" / "example"
    verifier.mkdir(parents=True)
    (verifier / "verify.py").write_text("def verify(): return 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "add", "gem/envs/example/verify.py"], check=True)
    subprocess.run(["git", "-C", str(source), "-c", "user.name=LOCA Test", "-c", "user.email=loca@example.invalid", "commit", "-qm", "tracked verifier"], check=True)

    original = adapter._verifier_sha256(source)
    cache = verifier / "__pycache__"
    cache.mkdir()
    (cache / "verify.cpython-312.pyc").write_bytes(b"generated bytecode")
    (verifier / "generated.py").write_text("generated = True\n", encoding="utf-8")

    assert adapter._verifier_sha256(source) == original
