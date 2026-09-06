"""Resilient seed-only supervisor for the pinned BEAM-10M Flash experiment.

It intentionally imports the unchanged BEAM runner: the supervisor's own
source is not part of a seed's provenance, so compatible checkpoints remain
reusable while failed conversations can be retried independently.
"""

from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from plugins.context_engine.scroll.evidence import run_qwen_flash_beam10m as beam


@dataclass(frozen=True)
class SeedSpec:
    conversation: str
    checkpoint_path: Path
    seed_path: Path
    provenance: Mapping[str, Any]
    expected_plans: tuple[str, ...]


def _seed_spec(conversation: str, *, experiment: Mapping[str, Any], experiment_digest: str, chats_root: Path, runtime_root: Path, plan_limit: int | None, execution_runner_sha256: str, runner_override: bool) -> SeedSpec:
    chat_path = chats_root / "10M" / conversation / "chat.json"
    chat = beam.live._read_json(chat_path)
    expected_plans = tuple(session for session, _ in beam._session_messages(chat, plan_limit))
    plan_label = "all" if plan_limit is None else str(plan_limit)
    seed_root = beam._seed_root(runtime_root, experiment_digest=experiment_digest, execution_runner_sha256=execution_runner_sha256, plan_label=plan_label, conversation=conversation)
    provenance = beam._seed_provenance(conversation, experiment=experiment, experiment_digest=experiment_digest, chat_path=chat_path, plan_label=plan_label, execution_runner_sha256=execution_runner_sha256, runner_override=runner_override)
    return SeedSpec(conversation, seed_root / "checkpoint.json", seed_root / "seed.json", provenance, expected_plans)


def _quarantine(path: Path) -> None:
    if not path.is_file():
        return
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        os.replace(path, path.with_name(f"{path.name}.invalid-{digest}"))
    except OSError as exc:
        raise beam.live.LiveRunError(f"could not quarantine invalid BEAM 10M seed artifact {path}") from exc


def _repair_invalid_seed(spec: SeedSpec) -> None:
    if spec.checkpoint_path.is_file() and beam._resume_seed_checkpoint(spec.checkpoint_path, spec.provenance, list(spec.expected_plans)) is None:
        _quarantine(spec.checkpoint_path)
    if spec.seed_path.is_file() and beam._resume_seed(spec.seed_path, spec.provenance, list(spec.expected_plans)) is None:
        _quarantine(spec.seed_path)


def run_seed_queue(conversations: Sequence[str], *, workers: int, retries: int, prepare: Callable[[str], Any], progress: Callable[..., None] = beam._progress) -> dict[str, Any]:
    """Run a bounded, backfilling queue with no concurrent duplicate conversation."""
    if not conversations or len(set(conversations)) != len(conversations) or workers <= 0 or retries < 0:
        raise beam.live.LiveRunError("BEAM 10M seed retry queue configuration is invalid")
    pending = deque(conversations)
    attempts = {conversation: 0 for conversation in conversations}
    completed: dict[str, Any] = {}
    exhausted: dict[str, Exception] = {}
    active: set[str] = set()
    futures: dict[Any, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        while pending or futures:
            while pending and len(futures) < workers:
                conversation = pending.popleft()
                if conversation in active or conversation in completed or conversation in exhausted:
                    raise beam.live.LiveRunError("BEAM 10M seed retry queue duplicated a conversation")
                attempts[conversation] += 1
                active.add(conversation)
                progress("seed-supervisor", "started", conversation=conversation, attempt=attempts[conversation], retries_remaining=max(0, retries - attempts[conversation] + 1))
                futures[executor.submit(prepare, conversation)] = conversation
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                conversation = futures.pop(future)
                active.remove(conversation)
                try:
                    completed[conversation] = future.result()
                    progress("seed-supervisor", "completed", conversation=conversation, attempt=attempts[conversation])
                except Exception as exc:
                    if attempts[conversation] <= retries:
                        pending.append(conversation)
                        progress("seed-supervisor", "requeued", conversation=conversation, attempt=attempts[conversation], retries_remaining=retries - attempts[conversation] + 1)
                    else:
                        exhausted[conversation] = exc
                        progress("seed-supervisor", "exhausted", conversation=conversation, attempt=attempts[conversation])
    if exhausted:
        failed = ", ".join(conversation for conversation in conversations if conversation in exhausted)
        raise beam.live.LiveRunError(f"BEAM 10M seed retries exhausted after draining the queue: {failed}") from next(iter(exhausted.values()))
    progress("seed-supervisor", "all-seeds-ready", conversations=list(conversations), attempts=attempts)
    return completed


def run(experiment_path: Path, *, chats_root: Path, runtime_root: Path, credential_home: Path, plan_limit: int | None, conversations: list[str] | None, seed_workers: int, seed_retries: int, accept_runner_sha: str | None) -> dict[str, Any]:
    experiment = beam._read_json(experiment_path, "BEAM 10M experiment manifest")
    beam._validate_experiment(experiment)
    execution_runner_sha256 = beam._sha256(Path(beam.__file__))
    runner_override = beam._runner_override_is_valid(str(experiment["runner_sha256"]), execution_runner_sha256, accept_runner_sha)
    if plan_limit is not None and (plan_limit <= 0 or plan_limit > 10):
        raise beam.live.LiveRunError("BEAM 10M plan limit is invalid")
    beam._validate_worker_count(seed_workers, "seed", experiment["max_parallel_workers"])
    if seed_retries < 0:
        raise beam.live.LiveRunError("BEAM 10M seed retry limit is invalid")
    beam.qwen._openrouter_api_key(credential_home)
    for conversation, expected in experiment["conversation_sha256"].items():
        if beam._sha256(chats_root / "10M" / conversation / "chat.json") != expected:
            raise beam.live.LiveRunError(f"BEAM 10M conversation hash does not match: {conversation}")
    selected = beam._select_conversations(experiment["conversations"], conversations)
    runtime_root = runtime_root.resolve()
    beam.live._secure_directory(runtime_root)
    beam.live._secure_directory(runtime_root / "seeds")
    experiment_digest = beam._canonical_sha256(experiment)
    specs = {conversation: _seed_spec(conversation, experiment=experiment, experiment_digest=experiment_digest, chats_root=chats_root, runtime_root=runtime_root, plan_limit=plan_limit, execution_runner_sha256=execution_runner_sha256, runner_override=runner_override) for conversation in selected}

    def prepare(conversation: str) -> Any:
        _repair_invalid_seed(specs[conversation])
        return beam._prepare_seed(conversation, experiment=experiment, experiment_digest=experiment_digest, chats_root=chats_root, runtime_root=runtime_root, credential_home=credential_home, plan_limit=plan_limit, execution_runner_sha256=execution_runner_sha256, runner_override=runner_override)

    beam._progress("seed-supervisor", "started", conversations=selected, seed_workers=seed_workers, seed_retries=seed_retries, execution_runner_sha256=execution_runner_sha256)
    seeds = run_seed_queue(selected, workers=seed_workers, retries=seed_retries, prepare=prepare)
    return {"conversations": selected, "completed": list(seeds), "seed_workers": seed_workers, "seed_retries": seed_retries, "execution_runner_sha256": execution_runner_sha256}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", required=True, type=Path)
    parser.add_argument("--beam-chats", required=True, type=Path)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--credential-home", type=Path, default=Path.home() / ".hermes")
    parser.add_argument("--plan-limit", type=int)
    parser.add_argument("--conversation", action="append")
    parser.add_argument("--seed-workers", type=int, default=1)
    parser.add_argument("--seed-retries", type=int, default=2)
    parser.add_argument("--accept-runner-sha")
    args = parser.parse_args()
    report = run(args.experiment, chats_root=args.beam_chats, runtime_root=args.runtime_root, credential_home=args.credential_home, plan_limit=args.plan_limit, conversations=args.conversation, seed_workers=args.seed_workers, seed_retries=args.seed_retries, accept_runner_sha=args.accept_runner_sha)
    print({"conversations": report["conversations"], "seed_workers": report["seed_workers"], "seed_retries": report["seed_retries"], "status": "all-seeds-ready"})


if __name__ == "__main__":
    main()
