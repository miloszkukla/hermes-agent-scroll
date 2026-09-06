"""Resumable, parallel orchestration for a future Hermes LOCA adaptation.

This module deliberately does not construct a model, launch LOCA MCP servers,
or claim paper reproduction.  A future adapter owns those actions.  The
orchestrator freezes the public LOCA task matrix, materializes one initial
snapshot per task, runs stock and Scroll jobs from clones of that snapshot, and
accepts only native-verifier-completed results for resume.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
from typing import Any, Callable, Mapping, Sequence

from .hermes_live import LiveRunError


LOCA_ADAPTATION_SCOPE = "hermes-loca-adaptation"
LOCA_SOURCE_COMMIT = "8b6fac49d9edd92922593e703b74ea255357c3ec"
LOCA_TASK_NAMES = frozenset({
    "ABTestingS2LEnv", "AcademicWarningS2LEnv", "ApplyPhDEmailS2LEnv", "CanvasArrangeExamS2LEnv",
    "CanvasListTestS2LEnv", "CourseAssistantS2LEnv", "ExcelMarketResearchS2LEnv", "FilterLowSellingProductsS2LEnv",
    "MachineOperatingS2LEnv", "NhlB2bAnalysisS2LEnv", "PayableInvoiceCheckerS2LEnv", "SetConfCrDdlS2LEnv",
    "UpdateMaterialInventoryS2LEnv", "WoocommerceNewWelcomeS2LEnv", "WoocommerceStockAlertS2LEnv",
})
LOCA_SEEDS = (42, 123, 456, 789, 2024)
LOCA_ARMS = ("stock", "scroll")
_SHA256_LENGTH = 64
_PREPARED_KEYS = frozenset({"schema_version", "provenance", "snapshot_path", "snapshot_sha256"})
_RESULT_KEYS = frozenset({"schema_version", "status", "provenance", "score", "trajectory_sha256", "final_state_sha256", "verifier_sha256"})


class LocaRunError(LiveRunError):
    """The LOCA adaptation could not preserve its frozen execution contract."""


@dataclass(frozen=True)
class LocaTask:
    name: str
    env_class: str
    seed: int
    context_size: str
    configuration_sha256: str
    mcp_servers_sha256: str

    @property
    def identifier(self) -> str:
        return f"loca/{self.context_size}/{self.name}/seed-{self.seed}"


@dataclass(frozen=True)
class PreparedLocaTask:
    task: LocaTask
    task_root: str
    snapshot_path: str
    snapshot_sha256: str


@dataclass(frozen=True)
class LocaJob:
    prepared: PreparedLocaTask
    arm: str
    provenance: Mapping[str, str]

    @property
    def identifier(self) -> str:
        return self.prepared.task.identifier


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
        raise LocaRunError(f"could not hash LOCA artifact {path}") from exc


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LocaRunError(f"could not read LOCA artifact {path}") from exc


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == _SHA256_LENGTH and all(character in "0123456789abcdef" for character in value)


def _relative_snapshot_path(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise LocaRunError("LOCA snapshot_path must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.parts[:1] != ("snapshots",):
        raise LocaRunError("LOCA snapshot_path must stay below snapshots")
    return path.as_posix()


def _snapshot_sha256(path: Path) -> str:
    if not path.is_dir() or path.is_symlink():
        raise LocaRunError("LOCA initial snapshot is unavailable")
    digest = hashlib.sha256()
    try:
        for entry in sorted(path.rglob("*")):
            relative = entry.relative_to(path).as_posix()
            if entry.is_symlink() or not entry.is_file():
                if entry.is_dir():
                    continue
                raise LocaRunError("LOCA initial snapshot contains an unsupported entry")
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            with entry.open("rb") as source:
                for block in iter(lambda: source.read(1 << 20), b""):
                    digest.update(block)
            digest.update(b"\0")
    except OSError as exc:
        raise LocaRunError("could not hash LOCA initial snapshot") from exc
    return digest.hexdigest()


def _secure_directory(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
        if not path.is_dir() or path.stat().st_mode & 0o077:
            raise OSError("directory permissions are not owner-only")
    except OSError as exc:
        raise LocaRunError(f"could not secure LOCA runtime directory {path}") from exc


def _clear_snapshot_directory(task_root: Path) -> None:
    snapshots = task_root / "snapshots"
    try:
        if snapshots.is_symlink():
            snapshots.unlink()
        elif snapshots.exists():
            shutil.rmtree(snapshots)
    except OSError as exc:
        raise LocaRunError("could not replace the stale LOCA initial snapshot") from exc


def _write_private_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(_canonical_json(value))
            handle.write("\n")
        os.replace(temporary, path)
        path.chmod(0o600)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise LocaRunError(f"could not atomically write LOCA artifact {path}") from exc


def _retire_active_report(path: Path) -> None:
    if not path.exists():
        return
    if path.is_symlink() or not path.is_file():
        raise LocaRunError("LOCA output path is not a regular report file")
    archive = path.with_name(f"{path.name}.previous-{_sha256_path(path)[:16]}")
    try:
        os.replace(path, archive)
    except OSError as exc:
        raise LocaRunError("could not retire the prior LOCA report") from exc


def _entry_task(entry: Any, *, context_size: str) -> LocaTask:
    if not isinstance(entry, Mapping) or set(entry) != {"name", "env_class", "env_params", "mcp_servers"}:
        raise LocaRunError("LOCA configuration entries must retain the public four-field shape")
    name, env_class, params, servers = entry["name"], entry["env_class"], entry["env_params"], entry["mcp_servers"]
    if not isinstance(name, str) or name not in LOCA_TASK_NAMES or not isinstance(env_class, str) or not env_class or not isinstance(params, Mapping) or not isinstance(params.get("seed"), int) or isinstance(params["seed"], bool) or params["seed"] not in LOCA_SEEDS or not isinstance(servers, Mapping):
        raise LocaRunError("LOCA configuration entry does not match the pinned task matrix")
    return LocaTask(name, env_class, params["seed"], context_size, _sha256_json(dict(entry)), _sha256_json(dict(servers)))


def load_loca_tasks(config_path: Path, *, context_size: str) -> tuple[LocaTask, ...]:
    """Load one exact public LOCA 75-state context-size configuration."""
    value = _read_json(config_path)
    if not isinstance(value, Mapping) or set(value) != {"configurations"} or not isinstance(value["configurations"], list):
        raise LocaRunError("LOCA configuration must contain only configurations")
    tasks = tuple(_entry_task(entry, context_size=context_size) for entry in value["configurations"])
    if len(tasks) != len(LOCA_TASK_NAMES) * len(LOCA_SEEDS):
        raise LocaRunError("LOCA configuration must retain all 75 task states")
    by_name: dict[str, set[int]] = {}
    identifiers: set[str] = set()
    for task in tasks:
        if task.identifier in identifiers:
            raise LocaRunError("LOCA configuration contains a duplicate task state")
        identifiers.add(task.identifier)
        by_name.setdefault(task.name, set()).add(task.seed)
    if set(by_name) != LOCA_TASK_NAMES or any(seeds != set(LOCA_SEEDS) for seeds in by_name.values()):
        raise LocaRunError("LOCA configuration must retain every task at every pinned seed")
    return tuple(sorted(tasks, key=lambda task: (task.name, task.seed)))


def verify_loca_checkout(loca_source: Path, *, expected_commit: str = LOCA_SOURCE_COMMIT) -> dict[str, str]:
    """Fail closed unless the public source checkout is exactly the frozen revision."""
    try:
        commit = subprocess.run(["git", "-C", str(loca_source), "rev-parse", "HEAD"], check=True, capture_output=True, text=True, timeout=30).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(loca_source), "status", "--porcelain", "--untracked-files=no"], check=True, capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise LocaRunError("could not verify the LOCA source checkout") from exc
    if commit != expected_commit or dirty:
        raise LocaRunError("LOCA source checkout does not match its pinned clean revision")
    return {"commit": commit, "license_sha256": _sha256_path(loca_source / "LICENSE")}


def preparation_provenance(task: LocaTask, *, plan_sha256: str, loca_config_sha256: str) -> dict[str, str]:
    if not all(_is_sha256(value) for value in (plan_sha256, loca_config_sha256)):
        raise LocaRunError("LOCA preparation provenance requires SHA-256 pins")
    return {"claim_scope": LOCA_ADAPTATION_SCOPE, "task_id": task.identifier, "task_configuration_sha256": task.configuration_sha256, "loca_config_sha256": loca_config_sha256, "plan_sha256": plan_sha256}


def job_provenance(prepared: PreparedLocaTask, *, arm: str, plan_sha256: str, verifier_sha256: str) -> dict[str, str]:
    if arm not in LOCA_ARMS or not all(_is_sha256(value) for value in (plan_sha256, verifier_sha256, prepared.snapshot_sha256)):
        raise LocaRunError("LOCA job provenance is incomplete")
    return {"claim_scope": LOCA_ADAPTATION_SCOPE, "task_id": prepared.task.identifier, "arm": arm, "task_configuration_sha256": prepared.task.configuration_sha256, "initial_snapshot_sha256": prepared.snapshot_sha256, "plan_sha256": plan_sha256, "verifier_sha256": verifier_sha256}


def _prepared_payload(value: Mapping[str, Any], provenance: Mapping[str, str], task: LocaTask, task_root: str) -> PreparedLocaTask | None:
    if not isinstance(value, Mapping) or set(value) != _PREPARED_KEYS or value.get("schema_version") != 1 or value.get("provenance") != dict(provenance) or not _is_sha256(value.get("snapshot_sha256")):
        return None
    try:
        snapshot_path = _relative_snapshot_path(value.get("snapshot_path"))
    except LocaRunError:
        return None
    return PreparedLocaTask(task, task_root, snapshot_path, value["snapshot_sha256"])


def _job_payload(value: Mapping[str, Any], provenance: Mapping[str, str]) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or set(value) != _RESULT_KEYS or value.get("schema_version") != 1 or value.get("status") != "completed" or value.get("provenance") != dict(provenance):
        return None
    score = value.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 1 or not all(_is_sha256(value.get(key)) for key in ("trajectory_sha256", "final_state_sha256", "verifier_sha256")):
        return None
    return dict(value)


def _task_directory(runtime_root: Path, provenance: Mapping[str, str]) -> Path:
    return runtime_root / "tasks" / _sha256_json(dict(provenance))


def prepared_snapshot_path(runtime_root: Path, prepared: PreparedLocaTask) -> Path:
    """Return the immutable source snapshot a future adapter must clone."""
    return runtime_root / "tasks" / prepared.task_root / prepared.snapshot_path


def _job_directory(runtime_root: Path, provenance: Mapping[str, str]) -> Path:
    return runtime_root / "jobs" / _sha256_json(dict(provenance))


def _prepare_phase(
    tasks: Sequence[LocaTask], *, runtime_root: Path, max_workers: int, plan_sha256: str,
    loca_config_sha256: str, materialize: Callable[[LocaTask, Path], Mapping[str, Any]], reuse_plan_sha256: str | None = None,
) -> dict[str, PreparedLocaTask]:
    if max_workers <= 0:
        raise LocaRunError("LOCA setup_workers must be positive")

    def prior_preparation(task: LocaTask, provenance: Mapping[str, str]) -> PreparedLocaTask | None:
        task_root = _task_directory(runtime_root, provenance)
        checkpoint = task_root / "prepared.json"
        try:
            prior = _prepared_payload(_read_json(checkpoint), provenance, task, task_root.name) if checkpoint.exists() else None
        except LocaRunError:
            prior = None
        if prior is not None:
            try:
                if _snapshot_sha256(prepared_snapshot_path(runtime_root, prior)) == prior.snapshot_sha256:
                    return prior
            except LocaRunError:
                pass
        return None

    def run_one(task: LocaTask) -> PreparedLocaTask:
        provenance = preparation_provenance(task, plan_sha256=plan_sha256, loca_config_sha256=loca_config_sha256)
        prior = prior_preparation(task, provenance)
        if prior is None and reuse_plan_sha256 is not None:
            prior = prior_preparation(task, preparation_provenance(task, plan_sha256=reuse_plan_sha256, loca_config_sha256=loca_config_sha256))
        if prior is not None:
            return prior
        task_root = _task_directory(runtime_root, provenance)
        _secure_directory(task_root)
        _clear_snapshot_directory(task_root)
        output = materialize(task, task_root)
        if not isinstance(output, Mapping) or set(output) != {"snapshot_path"}:
            raise LocaRunError(f"LOCA materializer produced an invalid snapshot for {task.identifier}")
        snapshot_path = _relative_snapshot_path(output["snapshot_path"])
        snapshot_sha256 = _snapshot_sha256(task_root / snapshot_path)
        _write_private_json(task_root / "prepared.json", {"schema_version": 1, "provenance": provenance, "snapshot_path": snapshot_path, "snapshot_sha256": snapshot_sha256})
        return PreparedLocaTask(task, task_root.name, snapshot_path, snapshot_sha256)

    completed: dict[str, PreparedLocaTask] = {}
    failures: list[tuple[str, Exception]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(run_one, task): task for task in tasks}
        for future in as_completed(futures):
            task = futures[future]
            try:
                completed[task.identifier] = future.result()
            except Exception as exc:
                failures.append((task.identifier, exc))
    if failures:
        names = ", ".join(identifier for identifier, _ in sorted(failures))
        raise LocaRunError(f"LOCA snapshot setup failed after draining all tasks: {names}: {failures[0][1]}") from failures[0][1]
    return completed


def run_loca_adaptation(
    tasks: Sequence[LocaTask], *, runtime_root: Path, output_path: Path, plan_sha256: str, runner_sha256: str,
    loca_config_sha256: str, verifier_sha256: str, setup_workers: int, job_workers: int,
    materialize: Callable[[LocaTask, Path], Mapping[str, Any]], execute: Callable[[LocaJob, Path], Mapping[str, Any]],
    reuse_prepared_plan_sha256: str | None = None, arms: Sequence[str] = LOCA_ARMS,
) -> dict[str, Any]:
    """Run a future adapter with task-level resume and one global bounded job queue.

    ``materialize`` must create one immutable snapshot below the task root and
    return its ``snapshots/...`` path. ``execute`` must clone that snapshot,
    run Hermes, stop the environment, and invoke the native verifier before
    returning its three artifact hashes and score.
    """
    if not tasks or len({task.identifier for task in tasks}) != len(tasks):
        raise LocaRunError("LOCA task list must be non-empty and unique")
    selected_arms = tuple(arms)
    if not selected_arms or len(set(selected_arms)) != len(selected_arms) or any(arm not in LOCA_ARMS for arm in selected_arms):
        raise LocaRunError("LOCA arms must be a non-empty unique subset of stock and scroll")
    if job_workers <= 0:
        raise LocaRunError("LOCA job_workers must be positive")
    if not all(_is_sha256(value) for value in (plan_sha256, runner_sha256, loca_config_sha256, verifier_sha256)):
        raise LocaRunError("LOCA run requires complete SHA-256 provenance")
    if reuse_prepared_plan_sha256 is not None and not _is_sha256(reuse_prepared_plan_sha256):
        raise LocaRunError("LOCA reusable preparation plan must be a SHA-256 pin")

    def progress(event: str, **fields: Any) -> None:
        print(json.dumps({"event": event, **fields}, sort_keys=True), flush=True)

    runtime_root = runtime_root.resolve()
    _secure_directory(runtime_root)
    _secure_directory(runtime_root / "tasks")
    _secure_directory(runtime_root / "jobs")
    _retire_active_report(output_path)
    prepared = _prepare_phase(tasks, runtime_root=runtime_root, max_workers=setup_workers, plan_sha256=plan_sha256, loca_config_sha256=loca_config_sha256, materialize=materialize, reuse_plan_sha256=reuse_prepared_plan_sha256)
    progress("loca_setup_complete", tasks=len(prepared), arms=list(selected_arms))
    jobs = [LocaJob(prepared[task.identifier], arm, job_provenance(prepared[task.identifier], arm=arm, plan_sha256=plan_sha256, verifier_sha256=verifier_sha256)) for task in sorted(tasks, key=lambda item: item.identifier) for arm in selected_arms]

    def run_one(index: int, job: LocaJob) -> tuple[int, dict[str, Any]]:
        job_root = _job_directory(runtime_root, job.provenance)
        _secure_directory(job_root)
        if _snapshot_sha256(prepared_snapshot_path(runtime_root, job.prepared)) != job.prepared.snapshot_sha256:
            raise LocaRunError(f"LOCA initial snapshot changed for {job.identifier}")
        result_path = job_root / "result.json"
        try:
            prior = _job_payload(_read_json(result_path), job.provenance) if result_path.exists() else None
        except LocaRunError:
            prior = None
        if prior is not None:
            progress("loca_job_resumed", arm=job.arm, task_id=job.identifier, score=float(prior["score"]))
            return index, {"task_id": job.identifier, "arm": job.arm, "score": float(prior["score"]), "resumed": True, "trajectory_sha256": prior["trajectory_sha256"], "final_state_sha256": prior["final_state_sha256"], "verifier_sha256": prior["verifier_sha256"]}
        progress("loca_job_started", arm=job.arm, task_id=job.identifier)
        outcome = execute(job, job_root)
        if not isinstance(outcome, Mapping) or set(outcome) != {"score", "trajectory_sha256", "final_state_sha256", "verifier_sha256"} or not all(_is_sha256(outcome.get(key)) for key in ("trajectory_sha256", "final_state_sha256", "verifier_sha256")):
            raise LocaRunError(f"LOCA executor produced an invalid native-verifier result for {job.identifier}")
        score = outcome["score"]
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 1 or outcome["verifier_sha256"] != verifier_sha256:
            raise LocaRunError(f"LOCA executor did not complete the pinned native verifier for {job.identifier}")
        result = {"schema_version": 1, "status": "completed", "provenance": dict(job.provenance), "score": float(score), "trajectory_sha256": outcome["trajectory_sha256"], "final_state_sha256": outcome["final_state_sha256"], "verifier_sha256": outcome["verifier_sha256"]}
        _write_private_json(result_path, result)
        progress("loca_job_completed", arm=job.arm, task_id=job.identifier, score=float(score))
        return index, {"task_id": job.identifier, "arm": job.arm, "score": float(score), "resumed": False, "trajectory_sha256": outcome["trajectory_sha256"], "final_state_sha256": outcome["final_state_sha256"], "verifier_sha256": outcome["verifier_sha256"]}

    rows_by_index: dict[int, dict[str, Any]] = {}
    failures: list[tuple[str, Exception]] = []
    with ThreadPoolExecutor(max_workers=job_workers) as executor:
        futures = {executor.submit(run_one, index, job): job for index, job in enumerate(jobs)}
        for future in as_completed(futures):
            job = futures[future]
            try:
                index, row = future.result()
                rows_by_index[index] = row
            except Exception as exc:
                progress("loca_job_failed", arm=job.arm, task_id=job.identifier, error=str(exc))
                failures.append((f"{job.arm}:{job.identifier}", exc))
    if failures:
        names = ", ".join(name for name, _ in sorted(failures))
        raise LocaRunError(f"LOCA jobs failed after draining the global queue: {names}: {failures[0][1]}") from failures[0][1]
    rows = [rows_by_index[index] for index in range(len(jobs))]
    if len(rows) != len(tasks) * len(selected_arms):
        raise LocaRunError("LOCA report requires the complete selected task-arm grid")
    report = {"schema_version": 1, "claim_scope": LOCA_ADAPTATION_SCOPE, "plan_sha256": plan_sha256, "runner_sha256": runner_sha256, "loca_config_sha256": loca_config_sha256, "verifier_sha256": verifier_sha256, "reused_prepared_plan_sha256": reuse_prepared_plan_sha256, "arms": list(selected_arms), "rows": rows, "resumed_rows": sum(row["resumed"] for row in rows)}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_private_json(output_path, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--loca-source", type=Path, required=True)
    parser.add_argument("--context-size", choices=("128k", "256k"), required=True)
    args = parser.parse_args()
    if not args.inspect:
        raise SystemExit("the Hermes LOCA adapter is not implemented; use --inspect only")
    source = verify_loca_checkout(args.loca_source)
    config_path = args.loca_source / "task-configs" / f"final_{args.context_size}_set_config.json"
    tasks = load_loca_tasks(config_path, context_size=args.context_size)
    print(json.dumps({"claim_scope": LOCA_ADAPTATION_SCOPE, "context_size": args.context_size, "loca": source, "config_sha256": _sha256_path(config_path), "task_states": len(tasks), "paired_jobs": len(tasks) * len(LOCA_ARMS)}, sort_keys=True))


if __name__ == "__main__":
    main()
