"""Fail-closed paired live evaluation for fixed objective coding trajectories."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping

from .coding_trajectories import CANONICAL_HISTORY_MIN_TOKENS, TRAJECTORIES, by_identifier, canonical_history_tokens, verify_workspace, write_workspace
from .hermes_live import LiveRunError, _lease_chatgpt_codex_access_token, _require_chatgpt_codex_oauth, _secure_directory, _write_private_json, coding_prompt_sha256, verify_manifest_provenance
from .live_manifest import validate_live_manifest


_REPEATS = 5
_BOOTSTRAP_RESAMPLES = 10_000
_SANDBOX_JOB_ROOT = Path("/work")
_RESUME_ATTESTATION_DIRECTORY = Path("plugins/context_engine/scroll/evidence")
_RESUME_SOURCE_KEYS = ("manifest_sha256", "implementation_commit", "runtime_root_name", "context_total_ceiling_seconds", "auxiliary_compression_timeout_seconds", "worker_timeout_seconds", "worker_access_token_minimum_ttl_seconds")


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LiveRunError(f"could not read coding manifest {path}") from exc
    if not isinstance(value, dict):
        raise LiveRunError("coding manifest must be a JSON object")
    return value


def _items(manifest: Mapping[str, Any]):
    datasets = manifest["datasets"]
    if len(datasets) != 1 or datasets[0]["name"] != "coding-trajectories":
        raise LiveRunError("coding manifest must freeze exactly coding-trajectories")
    identifiers = tuple(datasets[0]["item_ids"])
    expected = tuple(trajectory.identifier for trajectory in TRAJECTORIES)
    if identifiers != expected:
        raise LiveRunError("coding manifest must retain the complete fixed ordered trajectory set")
    items = tuple(by_identifier(identifier) for identifier in identifiers)
    if any(canonical_history_tokens(item) < CANONICAL_HISTORY_MIN_TOKENS for item in items):
        raise LiveRunError("coding trajectories must retain 100K-token canonical histories")
    return items


def _usage(value: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, float | int]:
    raw = value.get("usage")
    if not isinstance(raw, Mapping):
        raise LiveRunError("coding executor usage is unavailable")
    result = {}
    for key, limit in (("input_tokens", manifest["input_token_budget"]), ("output_tokens", manifest["output_token_budget"]), ("cache_read_tokens", manifest["cache_read_token_budget"])):
        number = raw.get(key)
        if not isinstance(number, (int, float)) or isinstance(number, bool) or number < 0 or number > limit:
            raise LiveRunError(f"coding executor usage.{key} violates the frozen budget")
        result[key] = number
    return result


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        raise LiveRunError("coding performance sample is empty")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def paired_bootstrap_lower_bound(deltas: list[float], *, seed: int, resamples: int = _BOOTSTRAP_RESAMPLES) -> float:
    if not deltas or resamples <= 0:
        raise LiveRunError("paired bootstrap requires completed paired outcomes")
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(deltas) for _ in deltas) / len(deltas) for _ in range(resamples))
    return means[max(0, math.ceil(0.05 * resamples) - 1)]


def _sandboxed_worker_command(job_root: Path, job_path: Path, workspace: Path) -> tuple[list[str], dict[str, str]]:
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        raise LiveRunError("coding evaluation requires bubblewrap")
    job_root = job_root.resolve()
    job_path = job_path.resolve()
    workspace = workspace.resolve()
    repository_root = Path(__file__).resolve().parents[2]
    try:
        repository_parts = repository_root.relative_to("/home").parts
    except ValueError as exc:
        raise LiveRunError("coding evaluation source must be beneath /home") from exc
    home_directories = []
    current = Path("/home")
    for part in repository_parts[:-1]:
        current /= part
        home_directories.extend(("--dir", str(current)))
    resolver_path = Path("/etc/resolv.conf").resolve()
    if not resolver_path.is_file():
        raise LiveRunError("coding evaluation DNS resolver is unavailable")
    resolver_directories = []
    if resolver_path.parent != Path("/etc"):
        current = Path("/")
        for part in resolver_path.parent.parts[1:]:
            current /= part
            resolver_directories.extend(("--dir", str(current)))
    environment = {"HOME": "/tmp", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PATH": os.pathsep.join((str(Path(sys.executable).parent), os.defpath)), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PYTHONPATH": str(repository_root)}
    return [
        bwrap, "--die-with-parent", "--new-session", "--unshare-pid",
        "--ro-bind", "/usr", "/usr", "--ro-bind", "/usr/local", "/usr/local", "--ro-bind", "/lib", "/lib", "--ro-bind", "/lib64", "/lib64", "--ro-bind", "/bin", "/bin", "--ro-bind", "/sbin", "/sbin", "--ro-bind", "/etc", "/etc", *resolver_directories, "--ro-bind", str(resolver_path), str(resolver_path), "--tmpfs", "/home", *home_directories, "--ro-bind", str(repository_root), str(repository_root), "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", str(_SANDBOX_JOB_ROOT),
        "--bind", str(job_root), str(_SANDBOX_JOB_ROOT), "--chdir", str(_SANDBOX_JOB_ROOT / "workspace"),
        sys.executable, "-m", "evals.scroll.hermes_live", "--worker", str(_SANDBOX_JOB_ROOT / "job.json"),
    ], environment


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _workspace_sha256(workspace: Path) -> str:
    if not workspace.is_dir():
        raise LiveRunError("coding resume workspace is unavailable")
    digest = hashlib.sha256()
    for path in sorted(workspace.rglob("*")):
        relative = path.relative_to(workspace).as_posix()
        if path.is_symlink() or not path.is_file():
            if path.is_dir():
                continue
            raise LiveRunError("coding resume workspace contains an unsupported entry")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1 << 20), b""):
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


def _resume_attestation(manifest: Mapping[str, Any], repository_root: Path) -> Mapping[str, Any]:
    sources = manifest["resume_sources"]
    jobs = {}
    for name, source in sources.items():
        path = repository_root / _RESUME_ATTESTATION_DIRECTORY / source["attestation_file"]
        try:
            if _sha256_file(path) != source["attestation_sha256"]:
                raise LiveRunError("coding resume attestation hash does not match the manifest")
            attestation = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LiveRunError("coding resume attestation is unavailable") from exc
        expected_keys = frozenset(("schema_version", "jobs", *_RESUME_SOURCE_KEYS))
        if not isinstance(attestation, Mapping) or set(attestation) != expected_keys or attestation.get("schema_version") != 1 or any(attestation.get(key) != source[key] for key in _RESUME_SOURCE_KEYS) or not isinstance(attestation.get("jobs"), Mapping):
            raise LiveRunError("coding resume attestation does not match the frozen source")
        for job_name, entry in attestation["jobs"].items():
            if job_name in jobs:
                raise LiveRunError("coding resume attestations contain duplicate jobs")
            jobs[job_name] = {"runtime_root_name": name, **entry}
    return {"jobs": jobs}


def _resumable_coding_result(resume_runtime_roots: Mapping[str, Path], manifest: Mapping[str, Any], attestation: Mapping[str, Any], job_name: str) -> Mapping[str, Any] | None:
    entry = attestation["jobs"].get(job_name)
    if entry is None:
        return None
    if not isinstance(entry, Mapping) or set(entry) != {"runtime_root_name", "result_sha256", "workspace_sha256"} or not isinstance(entry.get("runtime_root_name"), str) or entry["runtime_root_name"] not in resume_runtime_roots or not all(isinstance(entry[key], str) and len(entry[key]) == 64 and all(character in "0123456789abcdef" for character in entry[key]) for key in ("result_sha256", "workspace_sha256")):
        raise LiveRunError("coding resume attestation has an invalid job entry")
    root = resume_runtime_roots[entry["runtime_root_name"]]
    result_path = root / "jobs" / job_name / "result.json"
    workspace = root / "jobs" / job_name / "workspace"
    try:
        if _sha256_file(result_path) != entry["result_sha256"] or _workspace_sha256(workspace) != entry["workspace_sha256"]:
            raise LiveRunError("coding resume artifact does not match its attestation")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        usage = _usage(result, manifest)
    except (OSError, json.JSONDecodeError) as exc:
        raise LiveRunError("coding resume artifact is unavailable") from exc
    except LiveRunError:
        raise
    scenario_latency = result.get("scenario_latency_seconds") if isinstance(result, Mapping) else None
    if not isinstance(result, Mapping) or not isinstance(result.get("answer"), str) or not result["answer"].strip() or not isinstance(scenario_latency, (int, float)) or isinstance(scenario_latency, bool) or scenario_latency < 0:
        return None
    return {"answer": "verified-pass" if verify_workspace(workspace) else "verified-fail", "usage": usage, "elapsed_seconds": None, "scenario_latency_seconds": float(scenario_latency), "resumed": True}


def run_coding_evaluation(
    manifest_path: Path, *, runtime_root: Path, output_path: Path,
    credential_home: Path = Path.home() / ".hermes", resume_runtime_roots: tuple[Path, ...] = (),
) -> dict[str, Any]:
    manifest = _read_manifest(manifest_path)
    validate_live_manifest(manifest)
    if manifest["schema_version"] != 4:
        raise LiveRunError("coding evaluation requires schema_version 4")
    repository_root = Path(__file__).resolve().parents[2]
    verify_manifest_provenance(manifest, repository_root)
    if manifest["agent_prompt_sha256"] != coding_prompt_sha256():
        raise LiveRunError("coding manifest does not freeze this executor's agent prompt")
    if not credential_home.is_dir():
        raise LiveRunError("credential home is unavailable")
    _require_chatgpt_codex_oauth(credential_home)
    items = _items(manifest)
    scenarios = {item.identifier: item.scenario for item in items}
    runtime_root = runtime_root.resolve()
    _secure_directory(runtime_root)
    _secure_directory(runtime_root / "jobs")
    resume_roots = {path.resolve().name: path.resolve() for path in resume_runtime_roots}
    if len(resume_roots) != len(resume_runtime_roots) or set(resume_roots) != set(manifest["resume_sources"]) or any(path == runtime_root or not path.is_dir() for path in resume_roots.values()):
        raise LiveRunError("coding resume runtimes do not match the frozen sources")
    attestation = _resume_attestation(manifest, repository_root)

    def execute(arm: str, item, repeat: int) -> Mapping[str, Any]:
        probe = {"id": item.identifier, "type": item.category, "question": item.prompt}
        job_name = hashlib.sha256(f"{arm}:{item.identifier}:{repeat}".encode()).hexdigest()
        prior = _resumable_coding_result(resume_roots, manifest, attestation, job_name)
        if prior is not None:
            return prior
        job_root = runtime_root / "jobs" / job_name
        workspace = job_root / "workspace"
        write_workspace(item, workspace)
        _secure_directory(job_root)
        result_path = job_root / "result.json"
        job_path = job_root / "job.json"
        _write_private_json(job_path, {
            "lane": "coding", "arm": arm, "model": manifest["agent_model"], "context_window": manifest["context_window_tokens"],
            "max_iterations": manifest["max_iterations"], "temperature": manifest["temperature"], "seed": manifest["seed"], "max_output_tokens": manifest["max_output_tokens"], "context_total_ceiling_seconds": manifest["context_total_ceiling_seconds"], "auxiliary_compression_timeout_seconds": manifest["auxiliary_compression_timeout_seconds"], "output_token_budget": manifest["output_token_budget"], "cache_read_token_budget": manifest["cache_read_token_budget"],
            "history": item.history(), "probe": dict(probe), "scenario": item.scenario, "runtime_home": str(_SANDBOX_JOB_ROOT / "home"), "workspace": str(_SANDBOX_JOB_ROOT / "workspace"),
            "api_key": _lease_chatgpt_codex_access_token(credential_home, minimum_ttl_seconds=manifest["worker_access_token_minimum_ttl_seconds"]), "result_path": str(_SANDBOX_JOB_ROOT / "result.json"),
        })
        started = time.monotonic()
        try:
            command, environment = _sandboxed_worker_command(job_root, job_path, workspace)
            subprocess.run(command, cwd=workspace, env=environment, check=True, capture_output=True, text=True, timeout=manifest["worker_timeout_seconds"])
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            raise LiveRunError(f"Hermes {arm} coding arm failed for {item.identifier}") from exc
        finally:
            job_path.unlink(missing_ok=True)
        if not isinstance(result, dict) or not isinstance(result.get("answer"), str) or not isinstance(result.get("usage"), dict):
            raise LiveRunError(f"Hermes {arm} coding arm produced an invalid result")
        scenario_latency = result.get("scenario_latency_seconds")
        if not isinstance(scenario_latency, (int, float)) or isinstance(scenario_latency, bool) or scenario_latency < 0:
            raise LiveRunError(f"Hermes {arm} coding arm did not record scenario latency")
        return {"answer": "verified-pass" if verify_workspace(workspace) else "verified-fail", "usage": _usage(result, manifest), "elapsed_seconds": time.monotonic() - started, "scenario_latency_seconds": float(scenario_latency), "resumed": False}

    def run_one(index: int, item, repeat: int, arm: str) -> tuple[int, dict[str, Any]]:
        outcome = execute(arm, item, repeat)
        return index, {"task_id": item.identifier, "repeat": repeat + 1, "arm": arm, "score": float(outcome["answer"] == "verified-pass"), "answer_sha256": hashlib.sha256(outcome["answer"].encode()).hexdigest(), "usage": outcome["usage"], "elapsed_seconds": outcome["elapsed_seconds"], "scenario_latency_seconds": outcome["scenario_latency_seconds"], "resumed": outcome["resumed"]}

    jobs = [(index, item, repeat, arm) for index, (item, repeat, arm) in enumerate((item, repeat, arm) for item in items for repeat in range(_REPEATS) for arm in ("stock", "scroll"))]
    rows_by_index = {}
    executor = ThreadPoolExecutor(max_workers=manifest["max_parallel_workers"])
    futures = []
    try:
        futures = [executor.submit(run_one, *job) for job in jobs]
        for future in as_completed(futures):
            index, row = future.result()
            rows_by_index[index] = row
    except Exception:
        for future in futures:
            future.cancel()
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    rows = [rows_by_index[index] for index, _, _, _ in jobs]
    paired = {item.identifier: [] for item in items}
    for item in items:
        for repeat in range(1, _REPEATS + 1):
            outcomes = {row["arm"]: row["score"] for row in rows if row["task_id"] == item.identifier and row["repeat"] == repeat}
            if set(outcomes) != {"stock", "scroll"}:
                raise LiveRunError("coding evaluation requires complete paired outcomes")
            paired[item.identifier].append(outcomes["scroll"] - outcomes["stock"])
    task_deltas = [sum(paired[item.identifier]) / _REPEATS for item in items]
    stock_scores = [row["score"] for row in rows if row["arm"] == "stock"]
    scroll_scores = [row["score"] for row in rows if row["arm"] == "scroll"]
    manual_selection = [row["scenario_latency_seconds"] for row in rows if row["arm"] == "scroll" and scenarios[row["task_id"]] == "manual-compaction"]
    cache_rebuild = [row["scenario_latency_seconds"] for row in rows if row["arm"] == "scroll" and scenarios[row["task_id"]] == "cache-loss-resume"]
    lower_bound = paired_bootstrap_lower_bound(task_deltas, seed=int(manifest["seed"]))
    manifest_digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    report = {
        "manifest_sha256": manifest_digest, "billing_mode": manifest["billing_mode"], "rows": rows, "resumed_rows": sum(row["resumed"] for row in rows), "resume_sources": manifest["resume_sources"], "repeats_per_trajectory": _REPEATS,
        "task_success": {"stock_mean": sum(stock_scores) / len(stock_scores), "scroll_mean": sum(scroll_scores) / len(scroll_scores), "paired_delta_by_trajectory": dict(zip((item.identifier for item in items), task_deltas)), "paired_bootstrap_resamples": _BOOTSTRAP_RESAMPLES, "paired_delta_lower_95": lower_bound, "meets_minus_five_point_gate": lower_bound >= -0.05},
        "performance_seconds": {"scroll_manual_selection_p95": _percentile(manual_selection, 0.95), "scroll_cache_rebuild_p95": _percentile(cache_rebuild, 0.95), "meets_selection_gate": _percentile(manual_selection, 0.95) < 0.5, "meets_rebuild_gate": _percentile(cache_rebuild, 0.95) < 2.0},
    }
    report.update({
        "schema_version": 1, "implementation_commit": manifest["implementation_commit"], "agent_prompt_sha256": manifest["agent_prompt_sha256"],
        "source_revisions": manifest["source_revisions"], "licenses": manifest["licenses"],
        "trajectory_scenarios": scenarios,
    })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--resume-runtime-root", required=True, action="append", type=Path)
    args = parser.parse_args()
    report = run_coding_evaluation(args.manifest, runtime_root=args.runtime_root, output_path=args.output, resume_runtime_roots=tuple(args.resume_runtime_root))
    print(json.dumps({"manifest_sha256": report["manifest_sha256"], "billing_mode": report["billing_mode"], "rows": len(report["rows"])}, sort_keys=True))


if __name__ == "__main__":
    main()
