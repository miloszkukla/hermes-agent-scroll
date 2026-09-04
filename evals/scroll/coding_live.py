"""Fail-closed paired live evaluation for fixed objective coding trajectories."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from hermes_cli.env_loader import load_hermes_dotenv

from .coding_trajectories import TRAJECTORIES, by_identifier, verify_workspace, write_workspace
from .hermes_live import LiveRunError, coding_prompt_sha256
from .live_manifest import validate_live_manifest
from .paired_runner import PairedRunError, run_paired_evaluation


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
    return tuple(by_identifier(identifier) for identifier in identifiers)


def run_coding_evaluation(
    manifest_path: Path, *, runtime_root: Path, output_path: Path,
    credential_home: Path = Path.home() / ".hermes",
) -> dict[str, Any]:
    manifest = _read_manifest(manifest_path)
    validate_live_manifest(manifest)
    if manifest["agent_prompt_sha256"] != coding_prompt_sha256():
        raise LiveRunError("coding manifest does not freeze this executor's agent prompt")
    if not credential_home.is_dir():
        raise LiveRunError("credential home is unavailable")
    load_hermes_dotenv(hermes_home=credential_home, load_external_secrets=False)
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise LiveRunError("OpenRouter credential was not loaded")
    items = _items(manifest)
    by_id = {item.identifier: item for item in items}
    runtime_root.mkdir(parents=True, exist_ok=True)

    def execute(arm: str, probe: Mapping[str, str]) -> Mapping[str, Any]:
        item = by_id.get(probe["id"])
        if item is None or probe != {"id": item.identifier, "type": item.category, "question": item.prompt}:
            raise LiveRunError("coding executor received an unfrozen model probe")
        job_root = runtime_root / "jobs" / hashlib.sha256(f"{arm}:{item.identifier}".encode()).hexdigest()
        workspace = job_root / "workspace"
        write_workspace(item, workspace)
        result_path = job_root / "result.json"
        job_path = job_root / "job.json"
        job_path.write_text(json.dumps({
            "lane": "coding", "arm": arm, "model": manifest["agent_model"], "context_window": manifest["context_window_tokens"],
            "max_iterations": manifest["max_iterations"], "temperature": manifest["temperature"], "seed": manifest["seed"], "max_output_tokens": manifest["max_output_tokens"], "output_token_budget": manifest["output_token_budget"],
            "input_price_per_token": manifest["input_price_per_token"], "output_price_per_token": manifest["output_price_per_token"],
            "history": item.history(), "probe": dict(probe), "scenario": item.scenario, "runtime_home": str(job_root / "home"), "workspace": str(workspace),
            "credential_home": str(credential_home), "result_path": str(result_path),
        }), encoding="utf-8")
        try:
            subprocess.run([sys.executable, "-m", "evals.scroll.hermes_live", "--worker", str(job_path)], cwd=Path(__file__).resolve().parents[2], check=True, capture_output=True, text=True, timeout=1_200)
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            raise LiveRunError(f"Hermes {arm} coding arm failed for {item.identifier}") from exc
        if not isinstance(result, dict) or not isinstance(result.get("answer"), str) or not isinstance(result.get("usage"), dict):
            raise LiveRunError(f"Hermes {arm} coding arm produced an invalid result")
        return {"answer": "verified-pass" if verify_workspace(workspace) else "verified-fail", "usage": result["usage"]}

    probes = [{"id": item.identifier, "type": item.category, "question": item.prompt} for item in items]
    try:
        report = run_paired_evaluation(manifest, probes, execute, lambda _probe, answer: {"score": float(answer == "verified-pass")})
    except PairedRunError as exc:
        raise LiveRunError(str(exc)) from exc
    report.update({
        "schema_version": 1, "implementation_commit": manifest["implementation_commit"], "agent_prompt_sha256": manifest["agent_prompt_sha256"],
        "source_revisions": manifest["source_revisions"], "licenses": manifest["licenses"],
        "trajectory_scenarios": {item.identifier: item.scenario for item in items},
    })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = run_coding_evaluation(args.manifest, runtime_root=args.runtime_root, output_path=args.output)
    print(json.dumps({"manifest_sha256": report["manifest_sha256"], "total_cost_usd": report["total_cost_usd"], "rows": len(report["rows"])}, sort_keys=True))


if __name__ == "__main__":
    main()
