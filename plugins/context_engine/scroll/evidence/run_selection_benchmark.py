"""Record the locked warm Scroll selection benchmark without model access."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from evals.scroll.coding_trajectories import CANONICAL_HISTORY_MIN_TOKENS, TRAJECTORIES, canonical_history_tokens
from evals.scroll.hermes_live import LiveRunError, verify_manifest_provenance
from evals.scroll.live_manifest import validate_live_manifest
from plugins.context_engine.scroll.engine import ScrollContextEngine


_SCHEMA_VERSION = 1
_REPEATS = 5


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LiveRunError("selection benchmark manifest is unavailable") from exc
    if not isinstance(manifest, dict):
        raise LiveRunError("selection benchmark manifest must be an object")
    validate_live_manifest(manifest)
    if manifest.get("schema_version") != 4:
        raise LiveRunError("selection benchmark requires schema_version 4")
    return manifest


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _git_head(repository_root: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(repository_root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise LiveRunError("selection benchmark could not identify the evidence checkout") from exc


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * quantile)]


def _sample(item: Any, repeat: int, context_window_tokens: int) -> dict[str, Any]:
    history = list(item.history())
    history_tokens = canonical_history_tokens(item)
    if history_tokens < CANONICAL_HISTORY_MIN_TOKENS:
        raise LiveRunError("selection benchmark history is below the required scale")
    engine = ScrollContextEngine()
    engine.context_length = context_window_tokens
    try:
        engine.compress(history, force=True)
        started = time.monotonic()
        selected = engine.compress(history, force=True)
        return {"task_id": item.identifier, "repeat": repeat, "history_tokens": history_tokens, "selected_messages": len(selected), "seconds": time.monotonic() - started}
    finally:
        engine.on_session_end("selection-benchmark", [])


def run(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest = _read_manifest(manifest_path)
    verify_manifest_provenance(manifest, _REPOSITORY_ROOT)
    items = tuple(item for item in TRAJECTORIES if item.scenario == "manual-compaction")
    if len(items) != 6:
        raise LiveRunError("selection benchmark requires the six manual-compaction trajectories")
    script_path = Path(__file__).resolve()
    jobs = tuple((item, repeat) for item in items for repeat in range(1, _REPEATS + 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=manifest["max_parallel_workers"]) as executor:
        samples = list(executor.map(lambda job: _sample(*job, manifest["context_window_tokens"]), jobs))
    samples.sort(key=lambda sample: (sample["task_id"], sample["repeat"]))
    values = [float(sample["seconds"]) for sample in samples]
    report = {
        "schema_version": _SCHEMA_VERSION,
        "implementation_commit": manifest["implementation_commit"],
        "evidence_checkout_commit": _git_head(_REPOSITORY_ROOT),
        "manifest_sha256": _canonical_sha256(manifest),
        "runner_sha256": hashlib.sha256(script_path.read_bytes()).hexdigest(),
        "operation": "ScrollContextEngine.compress after one identical warm-up call",
        "context_window_tokens": manifest["context_window_tokens"],
        "max_parallel_workers": manifest["max_parallel_workers"],
        "repeats_per_trajectory": _REPEATS,
        "percentile_method": "sorted values at round((n - 1) * quantile)",
        "runtime": {
            "cpu_count": os.cpu_count(),
            "platform": platform.platform(aliased=True, terse=True),
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
        },
        "samples": samples,
        "p50_seconds": _percentile(values, 0.5),
        "p95_seconds": _percentile(values, 0.95),
        "max_seconds": max(values),
        "meets_selection_gate": _percentile(values, 0.95) < 0.5,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = run(args.manifest, args.output)
    print(json.dumps({"p95_seconds": report["p95_seconds"], "meets_selection_gate": report["meets_selection_gate"]}, sort_keys=True))


if __name__ == "__main__":
    main()
