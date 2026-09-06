"""Contracts for the non-live, resumable LOCA adaptation orchestrator."""

import hashlib
import json
import threading
import time

import pytest

from evals.scroll import loca_live


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _entry(name: str, seed: int) -> dict:
    return {"name": name, "env_class": f"gem.envs.{name}.{name}", "env_params": {"seed": seed}, "mcp_servers": {"mock": {"enabled": True}}}


def _config() -> dict:
    return {"configurations": [_entry(name, seed) for name in sorted(loca_live.LOCA_TASK_NAMES) for seed in loca_live.LOCA_SEEDS]}


def _tasks(tmp_path):
    path = tmp_path / "final_128k_set_config.json"
    path.write_text(json.dumps(_config()), encoding="utf-8")
    return loca_live.load_loca_tasks(path, context_size="128k"), path


def _run(tasks, tmp_path, *, plan="plan", runner="runner", materialize=None, execute=None, setup_workers=3, job_workers=3, reuse_prepared_plan=None, arms=loca_live.LOCA_ARMS):
    def default_materialize(task, root):
        snapshot = root / "snapshots" / f"{task.name}-{task.seed}"
        snapshot.mkdir(parents=True)
        (snapshot / "initial-state.txt").write_text(task.identifier, encoding="utf-8")
        return {"snapshot_path": f"snapshots/{task.name}-{task.seed}"}

    materialize = materialize or default_materialize
    execute = execute or (lambda job, _root: {"score": 1.0, "trajectory_sha256": _sha(f"trajectory:{job.arm}:{job.identifier}"), "final_state_sha256": _sha(f"state:{job.arm}:{job.identifier}"), "verifier_sha256": _sha("verifier")})
    return loca_live.run_loca_adaptation(tasks, runtime_root=tmp_path / "runtime", output_path=tmp_path / "report.json", plan_sha256=_sha(plan), runner_sha256=_sha(runner), loca_config_sha256=_sha("config"), verifier_sha256=_sha("verifier"), setup_workers=setup_workers, job_workers=job_workers, materialize=materialize, execute=execute, reuse_prepared_plan_sha256=(_sha(reuse_prepared_plan) if reuse_prepared_plan is not None else None), arms=arms)


def test_public_matrix_requires_all_75_pinned_task_states(tmp_path):
    tasks, _ = _tasks(tmp_path)

    assert len(tasks) == 75
    assert tasks[0].identifier == "loca/128k/ABTestingS2LEnv/seed-42"
    assert tasks[-1].identifier == "loca/128k/WoocommerceStockAlertS2LEnv/seed-2024"

    broken = _config()
    broken["configurations"].pop()
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(loca_live.LocaRunError, match="75 task states"):
        loca_live.load_loca_tasks(path, context_size="128k")


def test_setup_is_shared_by_arms_and_bounded(tmp_path):
    tasks, _ = _tasks(tmp_path)
    selected = tasks[:3]
    lock = threading.Lock()
    prepared, active, peak, snapshots = [], 0, 0, {}

    def materialize(task, root):
        nonlocal active, peak
        with lock:
            prepared.append(task.identifier)
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        snapshot = root / "snapshots" / f"{task.name}-{task.seed}"
        snapshot.mkdir(parents=True)
        (snapshot / "initial-state.txt").write_text(task.identifier, encoding="utf-8")
        return {"snapshot_path": f"snapshots/{task.name}-{task.seed}"}

    def execute(job, _root):
        snapshots[(job.identifier, job.arm)] = job.prepared.snapshot_sha256
        return {"score": 1.0, "trajectory_sha256": _sha(f"trajectory:{job.arm}:{job.identifier}"), "final_state_sha256": _sha(f"state:{job.arm}:{job.identifier}"), "verifier_sha256": _sha("verifier")}

    report = _run(selected, tmp_path, materialize=materialize, execute=execute, setup_workers=2)

    assert sorted(prepared) == sorted(task.identifier for task in selected)
    assert peak <= 2
    assert len(report["rows"]) == 6
    for task in selected:
        assert snapshots[(task.identifier, "stock")] == snapshots[(task.identifier, "scroll")]


def test_selected_arm_runs_only_that_complete_task_grid(tmp_path):
    tasks, _ = _tasks(tmp_path)
    called = []

    def execute(job, _root):
        called.append((job.arm, job.identifier))
        return {"score": 1.0, "trajectory_sha256": _sha(f"trajectory:{job.arm}:{job.identifier}"), "final_state_sha256": _sha(f"state:{job.arm}:{job.identifier}"), "verifier_sha256": _sha("verifier")}

    report = _run(tasks[:2], tmp_path, execute=execute, arms=("stock",))

    assert report["arms"] == ["stock"]
    assert set(called) == {("stock", task.identifier) for task in tasks[:2]}


def test_exact_completed_jobs_resume_and_corrupt_jobs_restart(tmp_path):
    tasks, _ = _tasks(tmp_path)
    selected = tasks[:2]
    calls = []

    def execute(job, _root):
        calls.append((job.arm, job.identifier))
        return {"score": 1.0, "trajectory_sha256": _sha(f"trajectory:{job.arm}:{job.identifier}"), "final_state_sha256": _sha(f"state:{job.arm}:{job.identifier}"), "verifier_sha256": _sha("verifier")}

    first = _run(selected, tmp_path, execute=execute)
    second = _run(selected, tmp_path, execute=execute)

    assert len(first["rows"]) == 4
    assert len(calls) == 4
    assert second["resumed_rows"] == 4

    corrupted = (tmp_path / "runtime" / "jobs" / sorted(path.name for path in (tmp_path / "runtime" / "jobs").iterdir())[0] / "result.json")
    corrupted.write_text("not json", encoding="utf-8")
    third = _run(selected, tmp_path, execute=execute)

    assert len(calls) == 5
    assert third["resumed_rows"] == 3


def test_changed_runner_sha_is_reported_but_does_not_restart_compatible_jobs(tmp_path):
    tasks, _ = _tasks(tmp_path)
    calls = []

    def execute(job, _root):
        calls.append((job.arm, job.identifier))
        return {"score": 1.0, "trajectory_sha256": _sha(f"trajectory:{job.arm}:{job.identifier}"), "final_state_sha256": _sha(f"state:{job.arm}:{job.identifier}"), "verifier_sha256": _sha("verifier")}

    _run(tasks[:1], tmp_path, runner="first", execute=execute)
    second = _run(tasks[:1], tmp_path, runner="second", execute=execute)

    assert len(calls) == 2
    assert second["resumed_rows"] == 2
    assert second["runner_sha256"] == _sha("second")


def test_execution_change_can_reuse_verified_prepared_snapshots(tmp_path):
    tasks, _ = _tasks(tmp_path)
    materialized, calls = [], []

    def materialize(task, root):
        materialized.append(task.identifier)
        snapshot = root / "snapshots" / "initial"
        snapshot.mkdir(parents=True)
        (snapshot / "state.txt").write_text(task.identifier, encoding="utf-8")
        return {"snapshot_path": "snapshots/initial"}

    def execute(job, _root):
        calls.append((job.arm, job.identifier))
        return {"score": 1.0, "trajectory_sha256": _sha(f"trajectory:{job.arm}:{job.identifier}"), "final_state_sha256": _sha(f"state:{job.arm}:{job.identifier}"), "verifier_sha256": _sha("verifier")}

    _run(tasks[:1], tmp_path, plan="before-execution-fix", materialize=materialize, execute=execute)
    second = _run(tasks[:1], tmp_path, plan="after-execution-fix", materialize=materialize, execute=execute, reuse_prepared_plan="before-execution-fix")

    assert materialized == [tasks[0].identifier]
    assert len(calls) == 4
    assert second["resumed_rows"] == 0
    assert second["reused_prepared_plan_sha256"] == _sha("before-execution-fix")


def test_changed_snapshot_is_rematerialized_and_cannot_reuse_results(tmp_path):
    tasks, _ = _tasks(tmp_path)
    selected = tasks[:1]
    materialized, calls, content = [], [], ["first"]

    def materialize(task, root):
        materialized.append(task.identifier)
        snapshot = root / "snapshots" / "initial"
        snapshot.mkdir(parents=True)
        (snapshot / "state.txt").write_text(content[0], encoding="utf-8")
        return {"snapshot_path": "snapshots/initial"}

    def execute(job, _root):
        calls.append((job.arm, job.identifier))
        return {"score": 1.0, "trajectory_sha256": _sha(f"trajectory:{job.arm}:{job.identifier}"), "final_state_sha256": _sha(f"state:{job.arm}:{job.identifier}"), "verifier_sha256": _sha("verifier")}

    _run(selected, tmp_path, materialize=materialize, execute=execute)
    snapshot = next((tmp_path / "runtime" / "tasks").iterdir()) / "snapshots" / "initial"
    (snapshot / "state.txt").write_text("tampered", encoding="utf-8")
    content[0] = "second"
    second = _run(selected, tmp_path, materialize=materialize, execute=execute)

    assert materialized == [selected[0].identifier, selected[0].identifier]
    assert len(calls) == 4
    assert second["resumed_rows"] == 0


def test_failed_rerun_retires_the_previous_report(tmp_path):
    tasks, _ = _tasks(tmp_path)
    _run(tasks[:1], tmp_path, runner="first")
    original = (tmp_path / "report.json").read_text(encoding="utf-8")

    def fail(_job, _root):
        raise RuntimeError("expected failure")

    with pytest.raises(loca_live.LocaRunError, match="after draining the global queue"):
        _run(tasks[:1], tmp_path, plan="second", execute=fail)

    archives = list(tmp_path.glob("report.json.previous-*"))
    assert not (tmp_path / "report.json").exists()
    assert len(archives) == 1
    assert archives[0].read_text(encoding="utf-8") == original


def test_global_job_queue_is_bounded_and_drains_failures_without_report(tmp_path):
    tasks, _ = _tasks(tmp_path)
    selected = tasks[:3]
    lock = threading.Lock()
    active, peak, called = 0, 0, []

    def execute(job, _root):
        nonlocal active, peak
        with lock:
            called.append((job.arm, job.identifier))
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        if job.arm == "scroll" and job.identifier == selected[0].identifier:
            raise RuntimeError("expected failure")
        return {"score": 1.0, "trajectory_sha256": _sha(f"trajectory:{job.arm}:{job.identifier}"), "final_state_sha256": _sha(f"state:{job.arm}:{job.identifier}"), "verifier_sha256": _sha("verifier")}

    with pytest.raises(loca_live.LocaRunError, match="after draining the global queue"):
        _run(selected, tmp_path, execute=execute, job_workers=2)

    assert peak <= 2
    assert set(called) == {(arm, task.identifier) for task in selected for arm in loca_live.LOCA_ARMS}
    assert not (tmp_path / "report.json").exists()


def test_completed_result_requires_pinned_native_verifier(tmp_path):
    tasks, _ = _tasks(tmp_path)

    def execute(job, _root):
        return {"score": 1.0, "trajectory_sha256": _sha(f"trajectory:{job.arm}:{job.identifier}"), "final_state_sha256": _sha(f"state:{job.arm}:{job.identifier}"), "verifier_sha256": _sha("different-verifier")}

    with pytest.raises(loca_live.LocaRunError, match="pinned native verifier"):
        _run(tasks[:1], tmp_path, execute=execute)
