#!/usr/bin/env python3
"""Run a resumable Hermes-native adaptation over the pinned public LOCA suite.

This is deliberately not the paper's QwenPaw/AgentZero evaluation.  It gives
stock Hermes and Hermes+Scroll the same public LOCA task, MCP tools, snapshot,
and native verifier, with every materialization and arm run in a fresh process.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import uuid
from typing import Any, Mapping, Sequence

_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from agent.codex_headers import CODEX_AUX_BASE_URL
from evals.scroll import loca_live


_ADAPTER_SCHEMA_VERSION = 1
_ADAPTER_PROTOCOL_REVISION = "hermes-loca-mcp-v11"
_SYSTEM_PROMPT_TEMPLATE = (
    "Complete the requested LOCA task with the provided task tools. "
    "Your only writable task workspace is {agent_workspace}; create or edit "
    "required artifacts only there. Before the final response, read back the "
    "exact required files from that workspace and verify their names and contents."
)
_COMPLETENESS_PROTOCOL = (
    " Treat quantified requirements such as all, each, complete, only, and "
    "every literally: do not substitute a sample, subset, or representative "
    "result. For large tabular work or structured documents, use the task "
    "Python executor when available to automate the full transformation and "
    "validation in the workspace. Before completing, independently check the "
    "artifact's required coverage, headers, ordering, filters, and requested "
    "side effects against the user task."
)
_TASK_DATA_PROTOCOL = (
    " The Python executor runs in the agent workspace. When a task-local MCP "
    "service fronts a large local dataset, its immutable input is available at "
    "../local_db for programmatic inspection; do not write there. If it "
    "contains a database, first use standard-library sqlite3 in read-only mode "
    "to inspect its schema and process the complete dataset; do not assume a "
    "cloud SDK or wildcard query is available. Keep all required artifacts and "
    "temporary code in the agent workspace. Match numerical units to artifact "
    "headers: percentage-labelled columns require percentage-scale values, not "
    "fractions."
)
_SCROLL_REQUIRED_POLICY = (
    " This is the Scroll-required arm. After gathering task-relevant evidence "
    "and before completing the task, call scroll_repl to search and inspect the "
    "relevant accumulated interaction history. Do not give a final response "
    "until you have used that result to check your work."
)
_REQUIRED_ENTRY_KEYS = frozenset({"name", "env_class", "env_params", "mcp_servers"})


class LocaAdapterError(loca_live.LocaRunError):
    """The Hermes-native LOCA adapter could not uphold its execution boundary."""


def _system_prompt(agent_workspace: Path, *, arm: str, has_python_executor: bool) -> str:
    if arm not in loca_live.LOCA_ARMS:
        raise LocaAdapterError("LOCA arm is invalid")
    prompt = _SYSTEM_PROMPT_TEMPLATE.format(agent_workspace=agent_workspace)
    if has_python_executor:
        prompt += _COMPLETENESS_PROTOCOL + _TASK_DATA_PROTOCOL
    return prompt + (_SCROLL_REQUIRED_POLICY if arm == "scroll" else "")


def _scroll_repl_call_count(messages: Any) -> int:
    if not isinstance(messages, list):
        return 0
    count = 0
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        calls = message.get("tool_calls")
        if not isinstance(calls, list):
            continue
        for call in calls:
            if not isinstance(call, Mapping):
                continue
            function = call.get("function")
            name = function.get("name") if isinstance(function, Mapping) else call.get("name")
            if name == "scroll_repl":
                count += 1
    return count


def _assert_scroll_required(messages: Any, *, arm: str) -> int:
    count = _scroll_repl_call_count(messages)
    if arm == "scroll" and count < 1:
        raise LocaAdapterError("Scroll-required arm completed without calling scroll_repl")
    return count


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


def _sha256_path(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise LocaAdapterError(f"could not hash LOCA artifact {path}") from exc


def _tree_sha256(path: Path) -> str:
    if not path.is_dir() or path.is_symlink():
        raise LocaAdapterError(f"LOCA artifact directory is unavailable: {path}")
    digest = hashlib.sha256()
    try:
        for entry in sorted(path.rglob("*")):
            relative = entry.relative_to(path).as_posix()
            if entry.is_symlink():
                raise LocaAdapterError(f"LOCA artifact contains a symlink: {relative}")
            if entry.is_dir():
                digest.update(f"D:{relative}\0".encode("utf-8"))
                continue
            if not entry.is_file():
                raise LocaAdapterError(f"LOCA artifact contains an unsupported entry: {relative}")
            digest.update(f"F:{relative}\0".encode("utf-8"))
            with entry.open("rb") as source:
                for block in iter(lambda: source.read(1 << 20), b""):
                    digest.update(block)
            digest.update(b"\0")
    except OSError as exc:
        raise LocaAdapterError(f"could not hash LOCA artifact directory {path}") from exc
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LocaAdapterError(f"could not read {label}: {path}") from exc


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(_canonical_json(value) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, path)
        path.chmod(0o600)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise LocaAdapterError(f"could not write private LOCA artifact {path}") from exc


def _secure_directory(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
        if not path.is_dir() or path.stat().st_mode & 0o077:
            raise OSError("directory permissions are not owner-only")
    except OSError as exc:
        raise LocaAdapterError(f"could not secure LOCA adapter directory {path}") from exc


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir() or source.is_symlink():
        raise LocaAdapterError(f"LOCA source directory is unavailable: {source}")
    if destination.exists() or destination.is_symlink():
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    try:
        shutil.copytree(source, destination, symlinks=False)
    except OSError as exc:
        raise LocaAdapterError(f"could not clone LOCA state from {source}") from exc


def _remove_path(path: Path) -> None:
    try:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.exists():
            shutil.rmtree(path)
    except OSError as exc:
        raise LocaAdapterError(f"could not remove stale LOCA state {path}") from exc


def _entry_key(entry: Mapping[str, Any]) -> tuple[str, int]:
    params = entry.get("env_params")
    if not isinstance(entry.get("name"), str) or not isinstance(params, Mapping) or not isinstance(params.get("seed"), int):
        raise LocaAdapterError("LOCA raw configuration entry is malformed")
    return entry["name"], params["seed"]


def load_raw_loca_entries(config_path: Path, tasks: Sequence[loca_live.LocaTask]) -> dict[tuple[str, int], dict[str, Any]]:
    """Load raw public entries and bind each one to its frozen LocaTask hash."""
    payload = _read_json(config_path, "LOCA configuration")
    entries = payload.get("configurations") if isinstance(payload, Mapping) else None
    if not isinstance(entries, list):
        raise LocaAdapterError("LOCA configuration has no configurations list")
    expected = {(task.name, task.seed): task for task in tasks}
    result: dict[tuple[str, int], dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != _REQUIRED_ENTRY_KEYS:
            raise LocaAdapterError("LOCA raw configuration entry changed shape")
        copied = dict(entry)
        key = _entry_key(copied)
        task = expected.get(key)
        if task is None:
            continue
        if _sha256_json(copied) != task.configuration_sha256:
            raise LocaAdapterError(f"LOCA raw configuration hash does not match {task.identifier}")
        if _sha256_json(dict(copied["mcp_servers"])) != task.mcp_servers_sha256:
            raise LocaAdapterError(f"LOCA raw MCP configuration hash does not match {task.identifier}")
        if key in result:
            raise LocaAdapterError(f"LOCA raw configuration repeats {task.identifier}")
        result[key] = copied
    if set(result) != set(expected):
        raise LocaAdapterError("LOCA raw configuration does not cover the selected task matrix")
    return result


def _selected_tasks(tasks: Sequence[loca_live.LocaTask], requested: Sequence[str]) -> list[loca_live.LocaTask]:
    if not requested:
        return list(tasks)
    wanted: set[tuple[str, int]] = set()
    for value in requested:
        name, separator, seed_text = value.rpartition(":")
        try:
            seed = int(seed_text)
        except ValueError as exc:
            raise LocaAdapterError("--task must be ENV_CLASS_NAME:SEED") from exc
        if not separator or not name:
            raise LocaAdapterError("--task must be ENV_CLASS_NAME:SEED")
        wanted.add((name, seed))
    selected = [task for task in tasks if (task.name, task.seed) in wanted]
    if len(selected) != len(wanted):
        raise LocaAdapterError("--task selects a state absent from the pinned LOCA configuration")
    return selected


def _adapter_source_root() -> Path:
    return _REPOSITORY_ROOT


def _controlled_path(loca_python: Path, inherited_path: str) -> str:
    entries = [str(loca_python.absolute().parent)]
    entries.extend(entry for entry in inherited_path.split(os.pathsep) if entry)
    return os.pathsep.join(dict.fromkeys(entries))


def _worker_environment(spec: Mapping[str, Any]) -> dict[str, str]:
    """Return the deliberately small environment handed to a worker process."""
    job_root = Path(str(spec["job_root"])).resolve()
    loca_source = Path(str(spec["loca_source"])).resolve()
    loca_python = Path(str(spec["loca_python"])).absolute()
    worker_path = str(spec["worker_path"])
    home = job_root / "home"
    hermes_home = job_root / "hermes-home"
    temporary = job_root / "tmp"
    for directory in (home, hermes_home, temporary):
        _secure_directory(directory)
    return {
        "HOME": str(home),
        "HERMES_HOME": str(hermes_home),
        "PATH": _controlled_path(loca_python, worker_path),
        "PYTHONPATH": os.pathsep.join((str(loca_source), str(_adapter_source_root()))),
        "TMPDIR": str(temporary),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    }


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _invoke_worker(mode: str, spec: Mapping[str, Any], *, timeout_seconds: int) -> dict[str, Any]:
    if timeout_seconds <= 0:
        raise LocaAdapterError("LOCA worker timeout must be positive")
    loca_python = Path(str(spec["loca_python"])).absolute()
    hermes_python = Path(str(spec.get("hermes_python", loca_python))).absolute()
    worker_python = hermes_python if mode == "hermes" else loca_python
    if not worker_python.is_file() or not os.access(worker_python, os.X_OK):
        raise LocaAdapterError("LOCA worker has no usable Python interpreter")
    job_root = Path(str(spec["job_root"])).resolve()
    _secure_directory(job_root)
    token = uuid.uuid4().hex
    spec_path = job_root / f".{mode}-{token}.json"
    output_path = job_root / f".{mode}-{token}.result.json"
    worker_spec = {**spec, "output_path": str(output_path)}
    _write_json(spec_path, worker_spec)
    environment = _worker_environment(worker_spec)
    command = [str(worker_python), str(Path(__file__).resolve()), f"--worker-{mode}", "--spec", str(spec_path)]
    process = subprocess.Popen(command, cwd=str(job_root), env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        _kill_process_group(process)
        raise LocaAdapterError(f"LOCA {mode} worker timed out after {timeout_seconds} seconds") from exc
    finally:
        spec_path.unlink(missing_ok=True)
    if process.returncode != 0:
        detail = [line for line in (stdout + "\n" + stderr).strip().splitlines() if line.strip()]
        suffix = f": {' | '.join(detail[-12:])}" if detail else ""
        raise LocaAdapterError(f"LOCA {mode} worker failed with exit {process.returncode}{suffix}")
    result = _read_json(output_path, f"LOCA {mode} worker result")
    output_path.unlink(missing_ok=True)
    if not isinstance(result, Mapping):
        raise LocaAdapterError(f"LOCA {mode} worker returned an invalid result")
    return dict(result)


def _replace_placeholders(value: Any, *, task_workspace: Path, agent_workspace: Path) -> Any:
    if isinstance(value, str):
        return value.replace("{task_workspace}", str(task_workspace)).replace("{agent_workspace}", str(agent_workspace))
    if isinstance(value, list):
        return [_replace_placeholders(item, task_workspace=task_workspace, agent_workspace=agent_workspace) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _replace_placeholders(item, task_workspace=task_workspace, agent_workspace=agent_workspace) for key, item in value.items()}
    return value


def _resolve_executable(command: str, *, worker_path: str, loca_python: Path) -> str:
    if command == "python":
        return str(loca_python.absolute())
    candidate = Path(command)
    if candidate.is_absolute():
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            raise LocaAdapterError(f"LOCA MCP executable is unavailable: {candidate}")
        return str(candidate)
    resolved = shutil.which(command, path=_controlled_path(loca_python, worker_path))
    if resolved is None:
        raise LocaAdapterError(f"LOCA MCP dependency '{command}' is unavailable on the worker PATH")
    return str(Path(resolved).resolve())


def _google_cloud_direct_launch(command: str, arguments: list[str], *, loca_source: Path, loca_python: Path) -> tuple[str, list[str]]:
    """Run LOCA's legacy Google Cloud server in the pinned LOCA environment.

    LOCA's public helper emits ``uv --directory ... run python server.py``.
    Its checked-in lock currently resolves MCP 2.x, while the server uses the
    MCP 1.x low-level API.  The pinned LOCA interpreter has that compatible
    MCP 1.x dependency already installed, so bypass only this incompatible
    launcher wrapper without changing the public server or its data inputs.
    """
    expected = ["--directory", str(loca_source / "mcp_convert"), "run", "python"]
    if command != "uv" or len(arguments) != 5 or arguments[:4] != expected:
        raise LocaAdapterError("LOCA Google Cloud server produced an unsupported launcher")
    script = Path(arguments[4]).resolve()
    expected_script = (loca_source / "mcp_convert" / "mcps" / "google_cloud" / "server.py").resolve()
    if script != expected_script or not script.is_file():
        raise LocaAdapterError("LOCA Google Cloud server script is unavailable")
    return str(loca_python), [str(script)]


def _require_python_executor_runtime(*, worker_path: str, loca_python: Path) -> None:
    _resolve_executable("uv", worker_path=worker_path, loca_python=loca_python)


def translate_loca_mcp_config(raw_entry: Mapping[str, Any], *, loca_source: Path, loca_python: Path, task_workspace: Path, worker_path: str) -> dict[str, dict[str, Any]]:
    """Build Hermes stdio-MCP entries from one exact public LOCA entry."""
    mcp_servers = raw_entry.get("mcp_servers")
    if not isinstance(mcp_servers, Mapping):
        raise LocaAdapterError("LOCA raw entry has no MCP server mapping")
    try:
        from gem.tools.mcp_server.config_loader import build_server_config
    except ModuleNotFoundError as exc:
        raise LocaAdapterError(f"LOCA Python dependency '{exc.name}' is unavailable while loading MCP configuration") from exc
    translated: dict[str, dict[str, Any]] = {}
    agent_workspace = task_workspace / "agent_workspace"
    for name, raw_server in mcp_servers.items():
        if not isinstance(name, str) or not isinstance(raw_server, Mapping):
            raise LocaAdapterError("LOCA MCP server configuration is malformed")
        if not bool(raw_server.get("enabled", True)):
            continue
        server_type = raw_server.get("type")
        params = raw_server.get("params", {})
        if not isinstance(server_type, str) or not isinstance(params, Mapping):
            raise LocaAdapterError(f"LOCA MCP server {name} has an invalid type or params")
        prepared = _replace_placeholders(dict(params), task_workspace=task_workspace, agent_workspace=agent_workspace)
        prepared["task_workspace"] = str(task_workspace)
        prepared["agent_workspace"] = str(agent_workspace)
        try:
            built = build_server_config(server_type=server_type, params=prepared, server_name=name)
        except (FileNotFoundError, ValueError, OSError) as exc:
            raise LocaAdapterError(f"could not build LOCA MCP server {name} ({server_type}): {exc}") from exc
        server = built.get(name)
        if not isinstance(server, Mapping) or not isinstance(server.get("command"), str) or not isinstance(server.get("args"), list):
            raise LocaAdapterError(f"LOCA MCP server {name} produced an invalid stdio specification")
        server_environment = server.get("env", {})
        if not isinstance(server_environment, Mapping) or not all(isinstance(key, str) and isinstance(value, str) for key, value in server_environment.items()):
            raise LocaAdapterError(f"LOCA MCP server {name} produced an invalid environment")
        command = server["command"]
        arguments = [str(argument) for argument in server["args"]]
        if server_type == "google_cloud":
            command, arguments = _google_cloud_direct_launch(command, arguments, loca_source=loca_source, loca_python=loca_python)
        if server_type == "terminal":
            if command != "uvx" or arguments != ["cli-mcp-server"]:
                raise LocaAdapterError("LOCA terminal MCP server differs from the pinned adapter contract")
            arguments = ["--from", "cli-mcp-server==0.2.5", "--with", "mcp<2", "cli-mcp-server"]
        if server_type == "pdf_tools":
            if command != "uvx" or not arguments or arguments[0] != "pdf-tools-mcp":
                raise LocaAdapterError("LOCA PDF MCP server differs from the pinned adapter contract")
            arguments = ["--from", "pdf-tools-mcp==0.1.4", "--with", "mcp<2", *arguments]
        if server_type == "python_execute":
            _require_python_executor_runtime(worker_path=worker_path, loca_python=loca_python)
        translated[name] = {
            "command": _resolve_executable(command, worker_path=worker_path, loca_python=loca_python),
            "args": arguments,
            "env": {**dict(server_environment), "PATH": _controlled_path(loca_python, worker_path), "PYTHONPATH": str(loca_source)},
            "enabled": True,
            "connect_timeout": 120,
            "timeout": 300,
        }
        if isinstance(server.get("cwd"), str):
            translated[name]["cwd"] = str(Path(server["cwd"]).resolve())
    if not translated:
        raise LocaAdapterError("LOCA task exposes no enabled MCP servers")
    return translated


def _load_worker_spec(path: Path) -> dict[str, Any]:
    spec = _read_json(path, "LOCA worker specification")
    try:
        path.unlink()
    except OSError as exc:
        raise LocaAdapterError("LOCA worker could not remove its private specification") from exc
    if not isinstance(spec, Mapping) or spec.get("schema_version") != _ADAPTER_SCHEMA_VERSION:
        raise LocaAdapterError("LOCA worker specification is invalid")
    return dict(spec)


def _worker_paths(spec: Mapping[str, Any]) -> tuple[Path, Path, Path, Path]:
    job_root = Path(str(spec["job_root"])).resolve()
    task_root = Path(str(spec["task_root"])).resolve()
    loca_source = Path(str(spec["loca_source"])).resolve()
    loca_python = Path(str(spec["loca_python"])).absolute()
    if not loca_source.is_dir() or not loca_python.is_file():
        raise LocaAdapterError("LOCA worker has no usable source checkout or Python interpreter")
    _secure_directory(job_root)
    return job_root, task_root, loca_source, loca_python


def _validate_worker_entry(spec: Mapping[str, Any]) -> dict[str, Any]:
    entry = spec.get("entry")
    expected = spec.get("task_configuration_sha256")
    if not isinstance(entry, Mapping) or set(entry) != _REQUIRED_ENTRY_KEYS or not isinstance(expected, str) or _sha256_json(dict(entry)) != expected:
        raise LocaAdapterError("LOCA worker raw entry does not match its frozen task configuration")
    return dict(entry)


def _environment_class(entry: Mapping[str, Any]) -> type[Any]:
    path = entry.get("env_class")
    if not isinstance(path, str) or "." not in path:
        raise LocaAdapterError("LOCA environment class path is invalid")
    module_name, class_name = path.rsplit(".", 1)
    try:
        module = importlib.import_module(module_name)
        value = getattr(module, class_name)
    except ModuleNotFoundError as exc:
        raise LocaAdapterError(f"LOCA Python dependency '{exc.name}' is unavailable while importing {path}") from exc
    except (ImportError, AttributeError) as exc:
        raise LocaAdapterError(f"could not import LOCA environment {path}") from exc
    if not isinstance(value, type):
        raise LocaAdapterError(f"LOCA environment {path} is not a class")
    return value


def _instantiate_environment(entry: Mapping[str, Any], task_workspace: Path) -> Any:
    params = entry.get("env_params")
    if not isinstance(params, Mapping):
        raise LocaAdapterError("LOCA environment parameters are invalid")
    prepared = _replace_placeholders(dict(params), task_workspace=task_workspace, agent_workspace=task_workspace / "agent_workspace")
    prepared["task_dir"] = str(task_workspace)
    return _environment_class(entry)(**prepared)


def _make_snapshot(task_workspace: Path, snapshot_root: Path) -> tuple[str, str]:
    agent_workspace = task_workspace / "agent_workspace"
    if not agent_workspace.is_dir() or agent_workspace.is_symlink():
        raise LocaAdapterError("LOCA environment did not materialize agent_workspace")
    groundtruth = task_workspace / "groundtruth_workspace"
    if groundtruth.exists() and (not groundtruth.is_dir() or groundtruth.is_symlink()):
        raise LocaAdapterError("LOCA environment materialized an invalid groundtruth_workspace")
    has_groundtruth = groundtruth.is_dir()
    execution = snapshot_root / "execution"
    verifier = snapshot_root / "verifier" / "groundtruth_workspace"
    _remove_path(snapshot_root)
    snapshot_root.mkdir(parents=True, mode=0o700)
    execution.mkdir(mode=0o700)
    for source in task_workspace.iterdir():
        if has_groundtruth and source.name == "groundtruth_workspace":
            continue
        destination = execution / source.name
        if source.is_symlink():
            raise LocaAdapterError("LOCA environment includes a symlink in execution state")
        if source.is_dir():
            _copy_tree(source, destination)
        elif source.is_file():
            shutil.copy2(source, destination)
        else:
            raise LocaAdapterError("LOCA environment includes an unsupported execution entry")
    if has_groundtruth:
        _copy_tree(groundtruth, verifier)
    execution_sha256 = _tree_sha256(execution)
    groundtruth_sha256 = _tree_sha256(verifier) if has_groundtruth else _sha256_bytes(b"groundtruth-absent")
    manifest = {"schema_version": 2, "execution_sha256": execution_sha256, "groundtruth_present": has_groundtruth, "groundtruth_sha256": groundtruth_sha256}
    _write_json(snapshot_root / "snapshot-manifest.json", manifest)
    return execution_sha256, loca_live._snapshot_sha256(snapshot_root)


def _restore_execution_state(snapshot_root: Path, task_workspace: Path) -> str:
    manifest = _read_json(snapshot_root / "snapshot-manifest.json", "LOCA snapshot manifest")
    expected = manifest.get("execution_sha256") if isinstance(manifest, Mapping) else None
    execution = snapshot_root / "execution"
    if not isinstance(expected, str) or len(expected) != 64 or _tree_sha256(execution) != expected:
        raise LocaAdapterError("LOCA prepared execution snapshot does not match its manifest")
    _remove_path(task_workspace)
    _copy_tree(execution, task_workspace)
    actual = _tree_sha256(task_workspace)
    if actual != expected:
        raise LocaAdapterError("LOCA job execution state is not the paired initial snapshot")
    if (task_workspace / "groundtruth_workspace").exists():
        raise LocaAdapterError("LOCA ground truth was exposed before Hermes started")
    return actual


def _stage_groundtruth(snapshot_root: Path, task_workspace: Path) -> str:
    manifest = _read_json(snapshot_root / "snapshot-manifest.json", "LOCA snapshot manifest")
    present = manifest.get("groundtruth_present") if isinstance(manifest, Mapping) else None
    expected = manifest.get("groundtruth_sha256") if isinstance(manifest, Mapping) else None
    if not isinstance(present, bool) or not isinstance(expected, str) or len(expected) != 64:
        raise LocaAdapterError("LOCA snapshot ground-truth manifest is invalid")
    source = snapshot_root / "verifier" / "groundtruth_workspace"
    destination = task_workspace / "groundtruth_workspace"
    if destination.exists() or destination.is_symlink():
        raise LocaAdapterError("LOCA ground truth appeared before verifier staging")
    if not present:
        if source.exists() or source.is_symlink() or expected != _sha256_bytes(b"groundtruth-absent"):
            raise LocaAdapterError("LOCA snapshot ground-truth absence does not match its manifest")
        return expected
    if _tree_sha256(source) != expected:
        raise LocaAdapterError("LOCA verifier ground truth does not match its manifest")
    _copy_tree(source, destination)
    if _tree_sha256(destination) != expected:
        raise LocaAdapterError("LOCA staged ground truth does not match its manifest")
    return expected


def _write_worker_result(spec: Mapping[str, Any], result: Mapping[str, Any]) -> None:
    output = Path(str(spec["output_path"])).resolve()
    _write_json(output, result)


def _worker_materialize(spec_path: Path) -> None:
    spec = _load_worker_spec(spec_path)
    job_root, task_root, _loca_source, _loca_python = _worker_paths(spec)
    entry = _validate_worker_entry(spec)
    scratch = job_root / "materialization"
    _remove_path(scratch)
    try:
        _instantiate_environment(entry, scratch)
        snapshot_root = task_root / "snapshots" / "public-initial-state"
        execution_sha256, snapshot_sha256 = _make_snapshot(scratch, snapshot_root)
    except Exception:
        log = scratch / "logs" / "env.log"
        failure_log = task_root / "materialization-failure.log"
        if log.is_file() and not log.is_symlink():
            shutil.copy2(log, failure_log)
            failure_log.chmod(0o600)
        raise
    finally:
        _remove_path(scratch)
    _write_worker_result(spec, {"snapshot_path": "snapshots/public-initial-state", "execution_sha256": execution_sha256, "snapshot_sha256": snapshot_sha256})


def _worker_config(mcp_servers: Mapping[str, Any], *, arm: str, context_window: int) -> str:
    config: dict[str, Any] = {"mcp_servers": dict(mcp_servers), "model": {"context_length": context_window}, "auxiliary": {"title_generation": {"enabled": False}}}
    if arm == "scroll":
        config["context"] = {"engine": "scroll", "compression": {"enabled": True, "threshold": 0.75}}
    return _canonical_json(config)


def _model_kwargs(spec: Mapping[str, Any]) -> dict[str, Any]:
    model = spec.get("model")
    if not isinstance(model, Mapping):
        raise LocaAdapterError("LOCA worker model specification is missing")
    provider = model.get("provider")
    api_key = model.get("api_key")
    name = model.get("name")
    if not all(isinstance(value, str) and value for value in (provider, api_key, name)):
        raise LocaAdapterError("LOCA worker model specification is invalid")
    if provider == "openai-codex":
        reasoning_config = model.get("reasoning_config")
        if reasoning_config is None:
            reasoning_config = {"enabled": False}
        if not isinstance(reasoning_config, Mapping):
            raise LocaAdapterError("LOCA Codex reasoning configuration is invalid")
        return {"provider": provider, "api_key": api_key, "base_url": CODEX_AUX_BASE_URL, "api_mode": "codex_responses", "model": name, "reasoning_config": dict(reasoning_config), "request_overrides": {}}
    if provider == "openrouter":
        return {"provider": provider, "api_key": api_key, "base_url": "https://openrouter.ai/api/v1", "api_mode": "chat_completions", "model": name, "reasoning_config": dict(model.get("reasoning_config") or {}), "request_overrides": dict(model.get("request_overrides") or {})}
    raise LocaAdapterError(f"LOCA adapter does not support provider {provider}")


def _assert_arm_semantics(agent: Any, arm: str, *, scroll_engine_type: type[Any] | None = None, compressor_type: type[Any] | None = None, scroll_tool_name: str | None = None) -> None:
    """Reject a plugin fallback or tool-surface leak before the first model call."""
    if arm not in loca_live.LOCA_ARMS:
        raise LocaAdapterError("LOCA worker arm is invalid")
    if scroll_engine_type is None or compressor_type is None or scroll_tool_name is None:
        from agent.context_compressor import ContextCompressor
        from plugins.context_engine.scroll.engine import SCROLL_REPL_TOOL_NAME, ScrollContextEngine

        scroll_engine_type = ScrollContextEngine
        compressor_type = ContextCompressor
        scroll_tool_name = SCROLL_REPL_TOOL_NAME
    engine = getattr(agent, "context_compressor", None)
    names = getattr(agent, "valid_tool_names", set())
    if not isinstance(names, set):
        raise LocaAdapterError("Hermes did not expose a valid tool registry")
    if arm == "scroll":
        if not isinstance(engine, scroll_engine_type) or getattr(engine, "name", None) != "scroll":
            raise LocaAdapterError("Scroll arm fell back instead of activating the Scroll context engine")
        if scroll_tool_name not in names:
            raise LocaAdapterError("Scroll arm did not expose scroll_repl")
        return
    if not isinstance(engine, compressor_type):
        raise LocaAdapterError("Stock arm did not activate the built-in ContextCompressor")
    if scroll_tool_name in names:
        raise LocaAdapterError("Stock arm leaked scroll_repl")


def _run_hermes(prompt: str, spec: Mapping[str, Any], *, task_workspace: Path, mcp_servers: Mapping[str, Any]) -> tuple[dict[str, Any], Path]:
    arm = spec.get("arm")
    if arm not in loca_live.LOCA_ARMS:
        raise LocaAdapterError("LOCA worker arm is invalid")
    context_window = spec.get("context_window")
    if not isinstance(context_window, int) or context_window <= 0:
        raise LocaAdapterError("LOCA worker context window is invalid")
    agent_workspace = task_workspace / "agent_workspace"
    if not agent_workspace.is_dir() or agent_workspace.is_symlink():
        raise LocaAdapterError("LOCA execution workspace is unavailable")
    hermes_home = Path(os.environ["HERMES_HOME"])
    _secure_directory(hermes_home)
    (hermes_home / "config.yaml").write_text(_worker_config(mcp_servers, arm=arm, context_window=context_window), encoding="utf-8")
    from hermes_state import SessionDB
    from run_agent import AIAgent
    from tools.mcp_tool import get_registered_mcp_server_names, register_mcp_servers, shutdown_mcp_servers

    names = sorted(mcp_servers)
    session_id = f"hermes-loca-{uuid.uuid4().hex}"
    database = None
    agent = None
    trajectory = Path(str(spec["job_root"])) / "trajectory.json"
    original_cwd = Path.cwd()
    try:
        os.chdir(agent_workspace)
        discovered = register_mcp_servers(dict(mcp_servers))
        registered = get_registered_mcp_server_names()
        if registered != set(names):
            raise LocaAdapterError(f"LOCA MCP registration mismatch: expected {', '.join(names)}; received {', '.join(sorted(registered))}")
        database = SessionDB(hermes_home / "state.db")
        database.create_session(session_id, source="eval", model=str(spec["model"]["name"]))
        enabled_toolsets = [*names, *( ["context_engine"] if arm == "scroll" else [])]
        agent = AIAgent(
            **_model_kwargs(spec), session_id=session_id, session_db=database, enabled_toolsets=enabled_toolsets,
            quiet_mode=True, skip_context_files=True, skip_memory=True, skip_background_review=True,
            platform="cli", max_iterations=int(spec["max_iterations"]), max_tokens=int(spec["max_output_tokens"]), fallback_model=[],
        )
        _assert_arm_semantics(agent, arm)
        response = agent.run_conversation(prompt, system_message=_system_prompt(agent_workspace, arm=arm, has_python_executor="python_execute" in mcp_servers), conversation_history=[], task_id=session_id)
        if not isinstance(response, Mapping) or response.get("failed") or not isinstance(response.get("final_response"), str) or not response["final_response"].strip():
            raise LocaAdapterError("Hermes did not end normally on the LOCA task")
        messages = response.get("messages", [])
        scroll_repl_calls = _scroll_repl_call_count(messages)
        _write_json(trajectory, {"final_response": response["final_response"], "messages": messages, "mcp_tools": discovered, "scroll_repl_calls": scroll_repl_calls})
        _assert_scroll_required(messages, arm=arm)
        return dict(response), trajectory
    finally:
        try:
            if agent is not None:
                agent.close()
        finally:
            try:
                shutdown_mcp_servers()
            finally:
                if database is not None:
                    database.close()
                os.chdir(original_cwd)


def _accept_verifier_result(value: Any) -> tuple[float, Mapping[str, Any]]:
    if not isinstance(value, tuple) or len(value) != 5:
        raise LocaAdapterError("LOCA native verifier returned an invalid result")
    _observation, reward, terminated, truncated, info = value
    if not isinstance(reward, (int, float)) or isinstance(reward, bool) or not 0 <= float(reward) <= 1:
        raise LocaAdapterError("LOCA native verifier returned an invalid score")
    if terminated is not True or truncated is True or not isinstance(info, Mapping):
        raise LocaAdapterError("LOCA native verifier did not terminate normally")
    return float(reward), dict(info)


def _worker_execute(spec_path: Path) -> None:
    spec = _load_worker_spec(spec_path)
    job_root, _task_root, loca_source, loca_python = _worker_paths(spec)
    entry = _validate_worker_entry(spec)
    snapshot_root = Path(str(spec["snapshot_root"])).resolve()
    expected_snapshot = spec.get("initial_snapshot_sha256")
    if not isinstance(expected_snapshot, str) or loca_live._snapshot_sha256(snapshot_root) != expected_snapshot:
        raise LocaAdapterError("LOCA shared initial snapshot changed before job start")
    task_workspace = job_root / "environment"
    _remove_path(task_workspace)
    env = _instantiate_environment(entry, task_workspace)
    _restore_execution_state(snapshot_root, task_workspace)
    mcp_servers = translate_loca_mcp_config(entry, loca_source=loca_source, loca_python=loca_python, task_workspace=task_workspace, worker_path=str(spec["worker_path"]))
    prompt = getattr(env, "_get_instructions", None)
    if not callable(prompt) or not isinstance((instruction := prompt()), str) or not instruction.strip():
        raise LocaAdapterError("LOCA environment did not provide a task instruction")
    timeout_seconds = spec.get("hermes_timeout_seconds")
    if not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
        raise LocaAdapterError("LOCA Hermes worker timeout is invalid")
    hermes_result = _invoke_worker("hermes", {**spec, "mcp_servers": mcp_servers, "prompt": instruction}, timeout_seconds=timeout_seconds)
    trajectory_sha256 = hermes_result.get("trajectory_sha256")
    if set(hermes_result) != {"trajectory_sha256"} or not isinstance(trajectory_sha256, str) or len(trajectory_sha256) != 64:
        raise LocaAdapterError("LOCA Hermes worker did not produce a trajectory receipt")
    groundtruth_sha256 = _stage_groundtruth(snapshot_root, task_workspace)
    score, verifier_info = _accept_verifier_result(env.step("hermes_final"))
    receipt = {"score": score, "info": verifier_info, "groundtruth_sha256": groundtruth_sha256}
    receipt_path = job_root / "verifier-receipt.json"
    _write_json(receipt_path, receipt)
    _write_worker_result(spec, {
        "score": score,
        "trajectory_sha256": trajectory_sha256,
        "final_state_sha256": _tree_sha256(task_workspace),
        "verifier_sha256": spec["verifier_sha256"],
        "verifier_receipt_sha256": _sha256_path(receipt_path),
    })


def _worker_hermes(spec_path: Path) -> None:
    spec = _load_worker_spec(spec_path)
    job_root, _task_root, _loca_source, _loca_python = _worker_paths(spec)
    prompt = spec.get("prompt")
    mcp_servers = spec.get("mcp_servers")
    if not isinstance(prompt, str) or not prompt.strip() or not isinstance(mcp_servers, Mapping):
        raise LocaAdapterError("LOCA Hermes worker specification is invalid")
    _response, trajectory = _run_hermes(prompt, spec, task_workspace=job_root / "environment", mcp_servers=mcp_servers)
    _write_worker_result(spec, {"trajectory_sha256": _sha256_path(trajectory)})


def _worker_preflight(spec_path: Path) -> None:
    spec = _load_worker_spec(spec_path)
    _job_root, _task_root, loca_source, loca_python = _worker_paths(spec)
    entries = spec.get("entries")
    if not isinstance(entries, list) or not entries:
        raise LocaAdapterError("LOCA preflight has no raw task entries")
    failures: list[str] = []
    for raw in entries:
        try:
            entry = _validate_worker_entry({"entry": raw, "task_configuration_sha256": _sha256_json(raw)})
            _environment_class(entry)
            translate_loca_mcp_config(entry, loca_source=loca_source, loca_python=loca_python, task_workspace=Path(str(spec["job_root"])) / "preflight-workspace", worker_path=str(spec["worker_path"]))
        except LocaAdapterError as exc:
            failures.append(str(exc))
    if failures:
        raise LocaAdapterError("LOCA preflight failed: " + "; ".join(sorted(set(failures))))
    _write_worker_result(spec, {"status": "structural-ready", "hermes_started": False, "mcp_servers_started": False})


def _semantic_plan_sha256(args: argparse.Namespace, *, config_sha256: str) -> str:
    return _sha256_json({
        "adapter_schema": _ADAPTER_SCHEMA_VERSION,
        "adapter_protocol": _ADAPTER_PROTOCOL_REVISION,
        "config_sha256": config_sha256,
        "loca_python": str(args.loca_python.absolute()),
        "hermes_python": str(args.hermes_python.absolute()),
        "provider": args.provider,
        "model": args.model,
        "trial": getattr(args, "trial", ""),
        "arms": list(_selected_arms(args)),
        "context_window": args.context_window,
        "max_iterations": args.max_iterations,
        "max_output_tokens": args.max_output_tokens,
        "setup_timeout_seconds": args.setup_timeout_seconds,
        "job_timeout_seconds": args.job_timeout_seconds,
        "reasoning_effort": args.reasoning_effort,
        "service_tier": args.service_tier,
        "system_prompt": _sha256_bytes((_SYSTEM_PROMPT_TEMPLATE + _COMPLETENESS_PROTOCOL + _TASK_DATA_PROTOCOL + _SCROLL_REQUIRED_POLICY).encode("utf-8")),
        "scroll_policy": "required-v1",
        "mcp_translation": "public-config-loader-v1-google-cloud-pinned-mcp1-python-executor-uv-validated-title-generation-disabled-workspace-cwd",
    })


def _selected_arms(args: argparse.Namespace) -> tuple[str, ...]:
    return tuple(getattr(args, "arms", None) or loca_live.LOCA_ARMS)


def _verifier_sha256(loca_source: Path) -> str:
    try:
        completed = subprocess.run(["git", "-C", str(loca_source), "ls-files", "-z", "--", "gem/envs"], check=True, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise LocaAdapterError("could not enumerate tracked LOCA verifier sources") from exc
    digest = hashlib.sha256()
    sources = [Path(value.decode("utf-8")) for value in completed.stdout.split(b"\0") if value]
    included = 0
    for relative in sorted(sources):
        if relative.suffix != ".py" or "__pycache__" in relative.parts:
            continue
        path = loca_source / relative
        if not path.is_file() or path.is_symlink():
            raise LocaAdapterError(f"tracked LOCA verifier source is unavailable: {relative.as_posix()}")
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
        included += 1
    if not included:
        raise LocaAdapterError("LOCA checkout has no tracked verifier sources")
    return digest.hexdigest()


def _api_key(args: argparse.Namespace) -> str:
    if args.provider == "openai-codex":
        from evals.scroll.hermes_live import _lease_chatgpt_codex_access_token

        return _lease_chatgpt_codex_access_token(args.credential_home)
    value = os.environ.get(args.api_key_env, "").strip()
    if not value:
        raise LocaAdapterError(f"LOCA OpenRouter credential is unavailable in {args.api_key_env}")
    return value


def _run(args: argparse.Namespace) -> dict[str, Any]:
    source = loca_live.verify_loca_checkout(args.loca_source)
    config_path = args.loca_source / "task-configs" / f"final_{args.context_size}_set_config.json"
    tasks = _selected_tasks(loca_live.load_loca_tasks(config_path, context_size=args.context_size), args.task)
    raw_entries = load_raw_loca_entries(config_path, tasks)
    arms = _selected_arms(args)
    config_sha256 = _sha256_path(config_path)
    plan_sha256 = _semantic_plan_sha256(args, config_sha256=config_sha256)
    verifier_sha256 = _verifier_sha256(args.loca_source)
    worker_base = {
        "schema_version": _ADAPTER_SCHEMA_VERSION,
        "loca_source": str(args.loca_source.resolve()),
        "loca_python": str(args.loca_python.absolute()),
        "hermes_python": str(args.hermes_python.absolute()),
        "worker_path": args.worker_path,
    }
    if args.preflight:
        preflight_root = args.runtime_root.resolve() / "preflight"
        result = _invoke_worker("preflight", {**worker_base, "job_root": str(preflight_root), "task_root": str(preflight_root), "entries": list(raw_entries.values())}, timeout_seconds=args.setup_timeout_seconds)
        if result != {"status": "structural-ready", "hermes_started": False, "mcp_servers_started": False}:
            raise LocaAdapterError("LOCA structural preflight returned an invalid lifecycle result")
        return {"status": "structural-ready", "hermes_started": False, "mcp_servers_started": False, "loca": source, "tasks": len(tasks), "arms": list(arms), "jobs": len(tasks) * len(arms)}

    def materialize(task: loca_live.LocaTask, task_root: Path) -> Mapping[str, Any]:
        entry = raw_entries[(task.name, task.seed)]
        result = _invoke_worker("materialize", {**worker_base, "job_root": str(task_root / "materializer"), "task_root": str(task_root), "entry": entry, "task_configuration_sha256": task.configuration_sha256}, timeout_seconds=args.setup_timeout_seconds)
        if result.get("snapshot_path") != "snapshots/public-initial-state":
            raise LocaAdapterError(f"LOCA materializer returned an invalid snapshot path for {task.identifier}")
        return {"snapshot_path": str(result["snapshot_path"])}

    def execute(job: loca_live.LocaJob, job_root: Path) -> Mapping[str, Any]:
        task = job.prepared.task
        entry = raw_entries[(task.name, task.seed)]
        snapshot_root = loca_live.prepared_snapshot_path(args.runtime_root.resolve(), job.prepared)
        result = _invoke_worker("execute", {
            **worker_base,
            "job_root": str(job_root),
            "task_root": str(args.runtime_root.resolve() / "tasks" / job.prepared.task_root),
            "snapshot_root": str(snapshot_root),
            "initial_snapshot_sha256": job.prepared.snapshot_sha256,
            "entry": entry,
            "task_configuration_sha256": task.configuration_sha256,
            "arm": job.arm,
            "context_window": args.context_window,
            "max_iterations": args.max_iterations,
            "max_output_tokens": args.max_output_tokens,
            "hermes_timeout_seconds": args.job_timeout_seconds,
            "verifier_sha256": verifier_sha256,
            "model": {"provider": args.provider, "name": args.model, "api_key": _api_key(args), "reasoning_config": ({"enabled": True, "effort": args.reasoning_effort} if args.reasoning_effort else {}), "request_overrides": ({"service_tier": args.service_tier} if args.service_tier else {})},
        }, timeout_seconds=args.job_timeout_seconds)
        expected = {"score", "trajectory_sha256", "final_state_sha256", "verifier_sha256", "verifier_receipt_sha256"}
        if set(result) != expected or not all(isinstance(result[field], str) and len(result[field]) == 64 for field in expected - {"score"}):
            raise LocaAdapterError(f"LOCA executor did not produce attested artifacts for {job.identifier}")
        return {field: result[field] for field in ("score", "trajectory_sha256", "final_state_sha256", "verifier_sha256")}

    report = loca_live.run_loca_adaptation(
        tasks, runtime_root=args.runtime_root, output_path=args.output, plan_sha256=plan_sha256,
        runner_sha256=_sha256_path(Path(__file__)), loca_config_sha256=config_sha256,
        verifier_sha256=verifier_sha256, setup_workers=args.setup_workers, job_workers=args.job_workers,
        materialize=materialize, execute=execute, reuse_prepared_plan_sha256=args.reuse_prepared_plan_sha256,
        arms=arms,
    )
    return {**report, "loca": source, "adapter": "hermes-native"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loca-source", type=Path)
    parser.add_argument("--loca-python", type=Path, default=Path(sys.executable))
    parser.add_argument("--hermes-python", type=Path, default=Path(sys.executable))
    parser.add_argument("--context-size", choices=("128k", "256k"), default="128k")
    parser.add_argument("--runtime-root", type=Path, default=Path(".scroll-runtime/live/loca-hermes"))
    parser.add_argument("--output", type=Path, default=Path(".scroll-runtime/reports/loca-hermes.json"))
    parser.add_argument("--task", action="append", default=[])
    parser.add_argument("--trial", default="")
    parser.add_argument("--arm", dest="arms", action="append", choices=loca_live.LOCA_ARMS, default=[])
    parser.add_argument("--provider", choices=("openai-codex", "openrouter"), default="openai-codex")
    parser.add_argument("--model", required=False, default="gpt-5.2-codex")
    parser.add_argument("--credential-home", type=Path, default=Path.home() / ".hermes")
    parser.add_argument("--api-key-env", default="OPENROUTER_API_KEY")
    parser.add_argument("--context-window", type=int, default=262144)
    parser.add_argument("--max-iterations", type=int, default=120)
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high", "xhigh", "max"))
    parser.add_argument("--service-tier", default="")
    parser.add_argument("--setup-workers", type=int, default=2)
    parser.add_argument("--job-workers", type=int, default=4)
    parser.add_argument("--setup-timeout-seconds", type=int, default=1800)
    parser.add_argument("--job-timeout-seconds", type=int, default=7200)
    parser.add_argument("--worker-path", default=os.environ.get("PATH", ""))
    parser.add_argument("--reuse-prepared-plan-sha256")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--worker-materialize", action="store_true")
    parser.add_argument("--worker-execute", action="store_true")
    parser.add_argument("--worker-hermes", action="store_true")
    parser.add_argument("--worker-preflight", action="store_true")
    parser.add_argument("--spec", type=Path)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    modes = [args.worker_materialize, args.worker_execute, args.worker_hermes, args.worker_preflight]
    if sum(modes) > 1 or (any(modes) and args.spec is None):
        raise SystemExit("exactly one worker mode requires --spec")
    if not any(modes) and args.loca_source is None:
        raise SystemExit("--loca-source is required outside worker mode")
    try:
        if args.worker_materialize:
            _worker_materialize(args.spec)
            return
        if args.worker_execute:
            _worker_execute(args.spec)
            return
        if args.worker_hermes:
            _worker_hermes(args.spec)
            return
        if args.worker_preflight:
            _worker_preflight(args.spec)
            return
        print(json.dumps(_run(args), sort_keys=True))
    except LocaAdapterError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
