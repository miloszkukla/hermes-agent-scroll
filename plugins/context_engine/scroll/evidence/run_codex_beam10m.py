"""Run a resumable Codex-OAuth BEAM-10M A/C comparison."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import selectors
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from evals.scroll import hermes_live as live
from plugins.context_engine.scroll.evidence import run_qwen_flash_beam10m as beam


_ARMS = ("A", "C")
_SCROLL_ARMS = frozenset({"C"})
_JUDGE_TIMEOUT_MIN_SECONDS = 600
_JUDGE_TIMEOUT_MAX_SECONDS = 3600
_JUDGE_PROGRAM = r'''
import json, sys, threading
from types import SimpleNamespace
from agent.auxiliary_client import resolve_provider_client

payload = json.load(sys.stdin)
usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0}
lock = threading.Lock()

def usage_value(value, name):
    return value.get(name, 0) if isinstance(value, dict) else getattr(value, name, 0)

class Judge:
    def __init__(self):
        self.client, self.model = resolve_provider_client("openai-codex", payload["model"], explicit_api_key=payload["api_key"], api_mode="codex_responses")
        if self.client is None or not self.model:
            raise RuntimeError("ChatGPT Codex OAuth judge client is unavailable")
    def invoke(self, prompt):
        messages = [{"role": "user", "content": prompt}] if isinstance(prompt, str) else list(prompt)
        reply = self.client.chat.completions.create(model=self.model, messages=messages, extra_body={"reasoning": payload["reasoning_config"]})
        if getattr(reply, "usage", None) is None:
            raise RuntimeError("judge response omitted usage")
        with lock:
            prompt_tokens = int(usage_value(reply.usage, "prompt_tokens") or 0)
            cache_read_tokens = int(usage_value(usage_value(reply.usage, "prompt_tokens_details"), "cached_tokens") or 0)
            completion_tokens = int(usage_value(reply.usage, "completion_tokens") or 0)
            if prompt_tokens <= 0 or completion_tokens <= 0:
                raise RuntimeError("judge response reported incomplete usage")
            usage["input_tokens"] += max(0, prompt_tokens - cache_read_tokens)
            usage["output_tokens"] += completion_tokens
            usage["cache_read_tokens"] += cache_read_tokens
        return SimpleNamespace(content=reply.choices[0].message.content or "")

judge = Judge()
from scroll_eval.evals.beam.judge.metrics import evaluate, primary_score
outcome = evaluate(payload["question_type"], payload["gold"].get("rubric", []), payload["answer"], judge, question=payload["gold"].get("question", ""), max_workers=1)
print(json.dumps({"score": primary_score(payload["question_type"], outcome), "usage": usage}))
'''


def _progress(stage: str, status: str, **fields: Any) -> None:
    print("PROGRESS " + json.dumps({"stage": stage, "status": status, **fields}, sort_keys=True), flush=True)


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise live.LiveRunError(f"could not hash {path}") from exc


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise live.LiveRunError(f"{label} is unavailable") from exc
    if not isinstance(value, dict):
        raise live.LiveRunError(f"{label} must be an object")
    return value


def _validate_runner_sha(job: Mapping[str, Any]) -> None:
    if job.get("execution_runner_sha256") != _sha256(Path(__file__)):
        raise live.LiveRunError("Codex BEAM 10M worker runner SHA does not match its job")


def _read_worker_job(job_path: Path) -> dict[str, Any]:
    job = _read_json(job_path, "Codex BEAM 10M worker job")
    if not isinstance(job.get("api_key"), str) or not job["api_key"].strip():
        raise live.LiveRunError("Codex BEAM 10M worker credential is unavailable")
    try:
        job_path.unlink()
    except OSError as exc:
        raise live.LiveRunError("Codex BEAM 10M worker credential could not be removed") from exc
    return job


def _worker_config(job: Mapping[str, Any]) -> str:
    engine = "scroll" if job["arm"] in _SCROLL_ARMS else "compressor"
    baseline_policy = (
        "  abort_on_summary_failure: true\n"
        "  protect_first_n: 0\n"
        f"  protect_last_n: {beam._A_MINIMUM_PROTECTED_TAIL_ROWS}\n"
        if job["arm"] == "A" else ""
    )
    return (
        "model:\n"
        f"  context_length: {job['context_window_tokens']}\n"
        "context:\n"
        f"  engine: {engine}\n"
        "compression:\n"
        "  enabled: true\n"
        f"{baseline_policy}"
        "  threshold: 0.75\n"
        "  context_timeout_seconds: 900\n"
        "  context_total_ceiling_seconds: 1800\n"
        "auxiliary:\n"
        "  compression:\n"
        "    provider: openai-codex\n"
        f"    model: {job['model']}\n"
        "    api_mode: codex_responses\n"
        f"    reasoning_effort: {job['reasoning_config']['effort']}\n"
        "    timeout: 900\n"
    )


def _open_runtime(job: Mapping[str, Any]) -> tuple[Any, Any, str]:
    runtime_home = Path(job["runtime_home"])
    runtime_home.mkdir(parents=True, exist_ok=True)
    (runtime_home / "config.yaml").write_text(_worker_config(job), encoding="utf-8")
    os.environ["HERMES_HOME"] = str(runtime_home)
    os.environ.pop("OPENROUTER_API_KEY", None)
    from hermes_state import SessionDB
    from run_agent import AIAgent

    db = SessionDB(runtime_home / "state.db")
    session_id = f"codex-beam10m-{uuid.uuid4().hex}"
    db.create_session(session_id, source="eval", model=job["model"])
    return AIAgent, db, session_id


def _build_agent(factory: Any, job: Mapping[str, Any], session_id: str, db: Any, toolsets: list[str]) -> Any:
    return factory(
        provider="openai-codex", api_key=job["api_key"], base_url=live.CODEX_AUX_BASE_URL, api_mode="codex_responses", model=job["model"], session_id=session_id, session_db=db,
        enabled_toolsets=toolsets, quiet_mode=True, skip_context_files=True, skip_memory=True, skip_background_review=True, platform="cli", max_iterations=int(job["max_iterations"]),
        max_tokens=int(job["max_output_tokens"]), reasoning_config=dict(job["reasoning_config"]), fallback_model=[],
    )


def _auxiliary_usage(db: Any, session_id: str, expected_model: str) -> tuple[int, int, int]:
    try:
        with db._read_ctx() as connection:
            rows = connection.execute("SELECT COALESCE(input_tokens, 0), COALESCE(output_tokens, 0), COALESCE(cache_read_tokens, 0), model, billing_provider FROM session_model_usage WHERE session_id = ? AND task <> ''", (session_id,)).fetchall()
        if any(row[3] != expected_model or row[4] not in {"", "openai-codex"} for row in rows):
            raise live.LiveRunError("Codex BEAM 10M auxiliary usage left ChatGPT OAuth")
        return tuple(sum(int(row[index] or 0) for row in rows) for index in range(3))
    except live.LiveRunError:
        raise
    except Exception as exc:
        raise live.LiveRunError("Codex BEAM 10M auxiliary usage is unavailable") from exc


def _current_usage(agent: Any, db: Any, session_id: str, model: str) -> dict[str, int]:
    auxiliary_input, auxiliary_output, auxiliary_cache_read = _auxiliary_usage(db, session_id, model)
    return {"input_tokens": int(getattr(agent, "session_input_tokens", 0) or 0) + auxiliary_input, "output_tokens": int(getattr(agent, "session_output_tokens", 0) or 0) + auxiliary_output, "cache_read_tokens": int(getattr(agent, "session_cache_read_tokens", 0) or 0) + auxiliary_cache_read}


def _add_usage(left: Mapping[str, int], right: Mapping[str, int]) -> dict[str, int]:
    return {field: int(left[field]) + int(right[field]) for field in ("input_tokens", "output_tokens", "cache_read_tokens")}


def _subtract_usage(left: Mapping[str, int], right: Mapping[str, int]) -> dict[str, int]:
    usage = {field: int(left[field]) - int(right[field]) for field in ("input_tokens", "output_tokens", "cache_read_tokens")}
    if any(value < 0 for value in usage.values()):
        raise live.LiveRunError("Codex BEAM 10M boundary usage decreased")
    return usage


def _seed_worker(job_path: Path) -> None:
    job = _read_worker_job(job_path)
    _validate_runner_sha(job)
    if job.get("arm") != "A":
        raise live.LiveRunError("Codex BEAM 10M seed worker only accepts arm A")
    chat = live._read_json(Path(job["chat_path"]))
    if not isinstance(chat, list):
        raise live.LiveRunError("Codex BEAM 10M seed chat is malformed")
    AIAgent, db, session_id = _open_runtime(job)
    from agent.aux_accounting import reset_accounting_context, set_accounting_context

    accounting_failures = []
    accounting_token = set_accounting_context(db, session_id, failure_sink=accounting_failures)
    agent = None
    try:
        agent = _build_agent(AIAgent, job, session_id, db, [])
        if getattr(agent, "provider", None) != "openai-codex" or getattr(agent, "api_mode", None) != "codex_responses" or getattr(agent, "model", None) != job["model"]:
            raise live.LiveRunError("Codex BEAM 10M seed left the ChatGPT OAuth route")
        sessions = list(beam._session_messages(chat))
        expected_plans = [session for session, _ in sessions]
        checkpoint_path = Path(job["checkpoint_path"])
        checkpoint = beam._resume_seed_checkpoint(checkpoint_path, job["result_provenance"], expected_plans)
        if checkpoint_path.exists() and checkpoint is None:
            raise live.LiveRunError(f"Codex BEAM 10M baseline checkpoint is invalid for conversation {job['conversation']}")
        active_history: list[dict[str, Any]] = checkpoint["history"] if checkpoint else []
        raw_rows = checkpoint["metadata"]["raw_rows"] if checkpoint else 0
        completed_plans = checkpoint["completed_plans"] if checkpoint else []
        boundaries = checkpoint["boundaries"] if checkpoint else []
        prior_usage = checkpoint["usage"] if checkpoint else {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0}
        if checkpoint:
            _progress("seed", "resumed", arm="A", conversation=job["conversation"], completed_plans=len(completed_plans), total_plans=len(sessions))
        for plan_index, (session, session_messages) in enumerate(sessions[len(completed_plans):], start=len(completed_plans) + 1):
            started = time.monotonic()
            _progress("seed-plan", "started", arm="A", conversation=job["conversation"], plan=session, plan_index=plan_index, total_plans=len(sessions))
            raw_rows += len(session_messages)
            active_history.extend(session_messages)
            input_history_sha256 = _canonical_sha256(active_history)
            usage_before = _current_usage(agent, db, session_id, job["model"])
            compacted, compression_count_after = beam._boundary_summary(agent, active_history, task_id=f"seed-{job['conversation']}-{session}")
            usage_after = _current_usage(agent, db, session_id, job["model"])
            boundary_usage = _subtract_usage(usage_after, usage_before)
            output_history_sha256 = _canonical_sha256(compacted)
            if boundary_usage["output_tokens"] <= 0 or input_history_sha256 == output_history_sha256:
                raise live.LiveRunError(f"Codex BEAM 10M baseline boundary evidence failed at {job['conversation']}/{session}")
            active_history = compacted
            completed_plans.append(session)
            boundaries.append({"plan": session, "input_history_sha256": input_history_sha256, "output_history_sha256": output_history_sha256, "summary_rows": beam._summary_rows(compacted), "compression_count_after": compression_count_after, "usage": boundary_usage})
            if accounting_failures:
                raise live.LiveRunError("Codex BEAM 10M boundary-compression accounting failed")
            usage = _add_usage(prior_usage, _current_usage(agent, db, session_id, job["model"]))
            live._write_private_json(checkpoint_path, beam._seed_payload(job, active_history, raw_rows, completed_plans, boundaries, usage))
            _progress("seed-plan", "checkpointed", arm="A", conversation=job["conversation"], plan=session, plan_index=plan_index, total_plans=len(sessions), elapsed_seconds=round(time.monotonic() - started, 1))
        if len(completed_plans) != len(expected_plans) or beam._seed_metadata(active_history, raw_rows, boundaries)["summary_rows"] <= 0 or accounting_failures:
            raise live.LiveRunError("Codex BEAM 10M baseline boundary compaction did not cover every plan")
        payload = beam._seed_payload(job, active_history, raw_rows, completed_plans, boundaries, _add_usage(prior_usage, _current_usage(agent, db, session_id, job["model"])))
        live._write_private_json(Path(job["result_path"]), payload)
        _progress("seed", "completed", arm="A", conversation=job["conversation"], completed_plans=len(completed_plans), total_plans=len(sessions))
    finally:
        reset_accounting_context(accounting_token)
        if agent is not None:
            agent.close()
        db.close()


def _worker(job_path: Path) -> None:
    job = _read_worker_job(job_path)
    _validate_runner_sha(job)
    arm = job.get("arm")
    if arm not in _ARMS:
        raise live.LiveRunError("Codex BEAM 10M worker arm is invalid")
    chat = live._read_json(Path(job["chat_path"]))
    if not isinstance(chat, list):
        raise live.LiveRunError("Codex BEAM 10M worker chat is malformed")
    AIAgent, db, session_id = _open_runtime(job)
    from agent.aux_accounting import reset_accounting_context, set_accounting_context

    accounting_failures = []
    accounting_token = set_accounting_context(db, session_id, failure_sink=accounting_failures)
    agent = None
    try:
        _progress("probe", "worker_started", arm=arm, conversation=job["conversation"], probe=job["probe"]["id"])
        seed_metadata = None
        if arm == "A":
            seed = _read_json(Path(job["seed_path"]), "Codex BEAM 10M baseline seed")
            if seed.get("provenance") != job.get("seed_provenance") or not isinstance(seed.get("history"), list) or not isinstance(seed.get("metadata"), dict):
                raise live.LiveRunError("Codex BEAM 10M baseline seed does not match its task")
            history = seed["history"]
            seed_metadata = seed["metadata"]
        else:
            sessions = list(beam._session_messages(chat))
            for plan_index, (session, session_messages) in enumerate(sessions, start=1):
                _progress("ingest-plan", "started", arm=arm, conversation=job["conversation"], probe=job["probe"]["id"], plan=session, plan_index=plan_index, total_plans=len(sessions))
                db.append_messages_batch(session_id, session_messages, chunk_rows=256)
                _progress("ingest-plan", "completed", arm=arm, conversation=job["conversation"], probe=job["probe"]["id"], plan=session, plan_index=plan_index, total_plans=len(sessions))
            history = []
        agent = _build_agent(AIAgent, job, session_id, db, ["context_engine"] if arm in _SCROLL_ARMS else [])
        if getattr(agent, "provider", None) != "openai-codex" or getattr(agent, "api_mode", None) != "codex_responses" or getattr(agent, "model", None) != job["model"]:
            raise live.LiveRunError("Codex BEAM 10M agent left the ChatGPT OAuth route")
        if arm in _SCROLL_ARMS:
            agent._publish_canonical_history_snapshot()
        prompt = beam.REQUIRED_SCROLL_PROMPT if arm == "C" else beam.ADVISORY_PROMPT
        _progress("probe", "model_started", arm=arm, conversation=job["conversation"], probe=job["probe"]["id"])
        response = agent.run_conversation(job["probe"]["question"], system_message=prompt, conversation_history=history)
        answer = response.get("final_response") if isinstance(response, dict) else None
        if not isinstance(answer, str) or not answer.strip() or (isinstance(response, dict) and response.get("failed")):
            raise live.LiveRunError("Codex BEAM 10M arm failed before a final answer")
        if int(getattr(agent, "session_api_calls", 0) or 0) <= 0 or int(getattr(agent, "session_output_tokens", 0) or 0) <= 0 or accounting_failures:
            raise live.LiveRunError("Codex BEAM 10M arm omitted valid OAuth usage")
        auxiliary_input, auxiliary_output, auxiliary_cache_read = _auxiliary_usage(db, session_id, job["model"])
        scroll_repl_calls = beam._tool_call_count(Path(job["runtime_home"]) / "state.db") if arm in _SCROLL_ARMS else 0
        if arm == "C" and scroll_repl_calls == 0:
            raise live.LiveRunError("Codex required Scroll arm answered without scroll_repl")
        payload = live._worker_result_payload(answer, int(getattr(agent, "session_input_tokens", 0) or 0) + auxiliary_input, int(getattr(agent, "session_output_tokens", 0) or 0) + auxiliary_output, int(getattr(agent, "session_cache_read_tokens", 0) or 0) + auxiliary_cache_read, 0.0, job["result_provenance"])
        payload.update({"scroll_repl_calls": scroll_repl_calls, "raw_history_supplied_to_agent": False, "seed_metadata": seed_metadata})
        live._write_private_json(Path(job["result_path"]), payload)
        _progress("probe", "answered", arm=arm, conversation=job["conversation"], probe=job["probe"]["id"], scroll_repl_calls=scroll_repl_calls)
    finally:
        reset_accounting_context(accounting_token)
        if agent is not None:
            agent.close()
        db.close()


def _validate_experiment(experiment: Mapping[str, Any]) -> None:
    required = {"schema_version", "experiment", "implementation_commit", "runner_sha256", "beam_adapter_sha256", "provider", "authentication_mode", "billing_mode", "api_mode", "agent_model", "judge_model", "reasoning_config", "context_window_tokens", "max_iterations", "max_output_tokens", "max_parallel_workers", "worker_timeout_seconds", "seed_timeout_seconds", "conversations", "conversation_sha256", "pilot_item_ids", "source_revisions"}
    if set(experiment) != required or experiment["schema_version"] != 1 or experiment["experiment"] != "codex-beam10m-raw-clearing":
        raise live.LiveRunError("Codex BEAM 10M manifest has an unexpected shape")
    if experiment["provider"] != "openai-codex" or experiment["authentication_mode"] != "chatgpt-oauth" or experiment["billing_mode"] != "chatgpt-subscription" or experiment["api_mode"] != "codex_responses":
        raise live.LiveRunError("Codex BEAM 10M manifest does not pin ChatGPT OAuth")
    if experiment["agent_model"] != "gpt-5.6-luna" or experiment["judge_model"] != "gpt-5.6-luna" or experiment["reasoning_config"] != {"enabled": True, "effort": "high"}:
        raise live.LiveRunError("Codex BEAM 10M model parameters do not match the agreed design")
    if experiment["conversations"] != ["8", "9", "10"] or set(experiment["conversation_sha256"]) != set(experiment["conversations"]):
        raise live.LiveRunError("Codex BEAM 10M manifest must pin conversations 8 through 10")
    if any(not isinstance(experiment[field], int) or isinstance(experiment[field], bool) or experiment[field] <= 0 for field in ("context_window_tokens", "max_iterations", "max_output_tokens", "max_parallel_workers", "worker_timeout_seconds", "seed_timeout_seconds")) or experiment["max_parallel_workers"] > 8:
        raise live.LiveRunError("Codex BEAM 10M numeric bounds are invalid")


def _runner_lineage(experiment: Mapping[str, Any], execution_runner_sha: str, accept_runner_sha: str | None) -> tuple[str, bool]:
    manifest_runner_sha = str(experiment["runner_sha256"])
    if execution_runner_sha == manifest_runner_sha:
        return manifest_runner_sha, False
    if accept_runner_sha != manifest_runner_sha:
        raise live.LiveRunError("Codex BEAM 10M execution code does not match its manifest")
    return manifest_runner_sha, True


def _seed_provenance(conversation: str, experiment: Mapping[str, Any], digest: str, chat_path: Path, runner_sha: str) -> dict[str, Any]:
    return {"experiment_manifest_sha256": digest, "implementation_commit": experiment["implementation_commit"], "runner_sha256": runner_sha, "arm": "A", "conversation": conversation, "history_sha256": _sha256(chat_path), "execution_plan_limit": "all"}


def _item_provenance(item: live.EvaluationItem, arm: str, experiment: Mapping[str, Any], digest: str, chat_path: Path, seed_path: Path | None, runner_sha: str) -> dict[str, Any]:
    provenance = {"experiment_manifest_sha256": digest, "implementation_commit": experiment["implementation_commit"], "runner_sha256": runner_sha, "arm": arm, "identifier": item.identifier, "model": experiment["agent_model"], "history_sha256": _sha256(chat_path), "probe_sha256": _canonical_sha256(item.public_probe), "execution_plan_limit": "all"}
    if seed_path is not None:
        provenance["seed_sha256"] = _sha256(seed_path)
    return provenance


def _seed_root(runtime_root: Path, digest: str, runner_sha: str, conversation: str) -> Path:
    return runtime_root / "seeds" / hashlib.sha256(f"{digest}:{runner_sha}:A:{conversation}".encode()).hexdigest()


def _job_root(runtime_root: Path, digest: str, runner_sha: str, arm: str, identifier: str) -> Path:
    return runtime_root / "jobs" / hashlib.sha256(f"{digest}:{runner_sha}:{arm}:{identifier}".encode()).hexdigest()


def _prepare_seed(conversation: str, experiment: Mapping[str, Any], digest: str, chats_root: Path, runtime_root: Path, credential_home: Path, runner_sha: str, execution_runner_sha: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    chat_path = chats_root / "10M" / conversation / "chat.json"
    chat = live._read_json(chat_path)
    if not isinstance(chat, list):
        raise live.LiveRunError(f"Codex BEAM 10M seed chat is malformed: {conversation}")
    expected_plans = [session for session, _ in beam._session_messages(chat)]
    seed_root = _seed_root(runtime_root, digest, runner_sha, conversation)
    live._secure_directory(seed_root)
    seed_path = seed_root / "seed.json"
    checkpoint_path = seed_root / "checkpoint.json"
    provenance = _seed_provenance(conversation, experiment, digest, chat_path, runner_sha)
    if beam._resume_seed(seed_path, provenance, expected_plans) is not None:
        _progress("seed", "reused", arm="A", conversation=conversation, completed_plans=len(expected_plans), total_plans=len(expected_plans))
        return seed_path, _read_json(seed_path, "Codex BEAM 10M seed"), provenance
    job_path = seed_root / "job.json"
    live._write_private_json(job_path, {"arm": "A", "conversation": conversation, "chat_path": str(chat_path), "model": experiment["agent_model"], "context_window_tokens": experiment["context_window_tokens"], "max_iterations": experiment["max_iterations"], "max_output_tokens": experiment["max_output_tokens"], "reasoning_config": experiment["reasoning_config"], "runtime_home": str(seed_root / "home"), "api_key": live._lease_chatgpt_codex_access_token(credential_home), "result_path": str(seed_path), "checkpoint_path": str(checkpoint_path), "result_provenance": provenance, "execution_runner_sha256": execution_runner_sha})
    try:
        _progress("seed", "queued", arm="A", conversation=conversation, completed_plans=0, total_plans=len(expected_plans))
        beam._run_child([sys.executable, str(Path(__file__).resolve()), "--seed-worker", str(job_path)], cwd=_REPOSITORY_ROOT, timeout=experiment["seed_timeout_seconds"], label=f"Codex BEAM 10M seed for conversation {conversation}")
    finally:
        job_path.unlink(missing_ok=True)
    seed = _read_json(seed_path, "Codex BEAM 10M seed")
    if beam._resume_seed(seed_path, provenance, expected_plans) is None:
        raise live.LiveRunError(f"Codex BEAM 10M seed is invalid for conversation {conversation}")
    return seed_path, seed, provenance


def _judge_item(item: live.EvaluationItem, answer: str, experiment: Mapping[str, Any], source_python: Path, scroll_source: Path, api_key: str, timeout: int) -> dict[str, Any]:
    payload = {"question_type": item.question_type, "gold": item.gold, "answer": answer, "model": experiment["judge_model"], "reasoning_config": experiment["reasoning_config"], "api_key": api_key}
    with tempfile.TemporaryDirectory(prefix="scroll-codex-judge-") as judge_home:
        environment = live._isolated_subprocess_environment()
        environment["HERMES_HOME"] = judge_home
        try:
            process = subprocess.run([str(source_python), "-c", _JUDGE_PROGRAM], input=json.dumps(payload), text=True, cwd=scroll_source, env=environment, capture_output=True, check=True, timeout=timeout)
            result = json.loads(process.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            raise live.LiveRunError("pinned BEAM Codex judge failed") from exc
    usage = result.get("usage") if isinstance(result, dict) else None
    if not isinstance(result, dict) or not isinstance(result.get("score"), (int, float)) or isinstance(result.get("score"), bool) or not isinstance(usage, dict):
        raise live.LiveRunError("pinned BEAM Codex judge returned an invalid result")
    if any(not isinstance(usage.get(field), int) or isinstance(usage[field], bool) or usage[field] < 0 for field in ("input_tokens", "output_tokens", "cache_read_tokens")) or usage["output_tokens"] <= 0:
        raise live.LiveRunError("pinned BEAM Codex judge returned invalid usage")
    return {"score": float(result["score"]), "usage": {field: usage[field] for field in ("input_tokens", "output_tokens", "cache_read_tokens")}}


def _judge_lineage(experiment: Mapping[str, Any], scroll_commit: str, timeout: int) -> dict[str, Any]:
    return {"model": experiment["judge_model"], "reasoning_config": experiment["reasoning_config"], "judge_program_sha256": hashlib.sha256(_JUDGE_PROGRAM.encode()).hexdigest(), "scroll_commit": scroll_commit, "judge_timeout_seconds": timeout}


def _resume_row(row_path: Path, result: Mapping[str, Any], provenance: Mapping[str, Any], arm: str, judge_lineage: Mapping[str, Any]) -> dict[str, Any] | None:
    try:
        row = _read_json(row_path, "Codex BEAM 10M result row")
    except live.LiveRunError:
        return None
    usage = row.get("usage")
    judge_usage = row.get("judge_usage")
    valid_usage = lambda value: isinstance(value, dict) and all(isinstance(value.get(field), int) and not isinstance(value[field], bool) and value[field] >= 0 for field in ("input_tokens", "output_tokens", "cache_read_tokens"))
    if row.get("provenance") != dict(provenance) or row.get("judge_lineage") != dict(judge_lineage) or row.get("answer_sha256") != hashlib.sha256(str(result.get("answer", "")).encode()).hexdigest() or not isinstance(row.get("score"), (int, float)) or isinstance(row.get("score"), bool) or not valid_usage(usage) or not valid_usage(judge_usage):
        return None
    if arm == "C" and int(row.get("scroll_repl_calls", 0) or 0) <= 0:
        return None
    return row


def _run_item(arm: str, item: live.EvaluationItem, experiment: Mapping[str, Any], digest: str, chats_root: Path, scroll_source: Path, source_python: Path, runtime_root: Path, credential_home: Path, seeds: Mapping[str, tuple[Path, dict[str, Any], dict[str, Any]]], runner_sha: str, execution_runner_sha: str, judge_lineage: Mapping[str, Any]) -> dict[str, Any]:
    conversation = beam._conversation_from_identifier(item.identifier)
    chat_path = chats_root / "10M" / conversation / "chat.json"
    seed_path = seeds[conversation][0] if arm == "A" else None
    provenance = _item_provenance(item, arm, experiment, digest, chat_path, seed_path, runner_sha)
    job_root = _job_root(runtime_root, digest, runner_sha, arm, item.identifier)
    live._secure_directory(job_root)
    result_path, row_path = job_root / "result.json", job_root / "row.json"
    result = live._resumable_worker_result(result_path, provenance) if result_path.is_file() else None
    if result is None:
        job_path = job_root / "job.json"
        job = {"arm": arm, "conversation": conversation, "chat_path": str(chat_path), "model": experiment["agent_model"], "context_window_tokens": experiment["context_window_tokens"], "max_iterations": experiment["max_iterations"], "max_output_tokens": experiment["max_output_tokens"], "reasoning_config": experiment["reasoning_config"], "probe": item.public_probe, "runtime_home": str(job_root / "home"), "api_key": live._lease_chatgpt_codex_access_token(credential_home), "result_path": str(result_path), "result_provenance": provenance, "execution_runner_sha256": execution_runner_sha}
        if arm == "A":
            job.update({"seed_path": str(seeds[conversation][0]), "seed_provenance": seeds[conversation][2]})
        live._write_private_json(job_path, job)
        try:
            _progress("probe", "queued", arm=arm, conversation=conversation, probe=item.identifier)
            beam._run_child([sys.executable, str(Path(__file__).resolve()), "--worker", str(job_path)], cwd=_REPOSITORY_ROOT, timeout=experiment["worker_timeout_seconds"], label=f"Codex BEAM 10M {arm} worker for {item.identifier}")
        finally:
            job_path.unlink(missing_ok=True)
        result = live._resumable_worker_result(result_path, provenance)
    if result is None or (arm == "C" and (result.get("raw_history_supplied_to_agent") is not False or int(result.get("scroll_repl_calls", 0) or 0) <= 0)):
        raise live.LiveRunError(f"Codex BEAM 10M worker result is invalid for {item.identifier}")
    if (row := _resume_row(row_path, result, provenance, arm, judge_lineage)) is not None:
        _progress("probe", "reused", arm=arm, conversation=conversation, probe=item.identifier)
        return row
    _progress("judge", "started", arm=arm, conversation=conversation, probe=item.identifier)
    verdict = _judge_item(item, result["answer"], experiment, source_python, scroll_source, live._lease_chatgpt_codex_access_token(credential_home), int(judge_lineage["judge_timeout_seconds"]))
    row = {"task_id": item.identifier, "score": verdict["score"], "answer_sha256": hashlib.sha256(result["answer"].encode()).hexdigest(), "usage": result["usage"], "judge_usage": verdict["usage"], "scroll_repl_calls": int(result.get("scroll_repl_calls", 0) or 0), "seed_metadata": result.get("seed_metadata"), "judge_lineage": dict(judge_lineage), "provenance": provenance}
    live._write_private_json(row_path, row)
    _progress("probe", "scored", arm=arm, conversation=conversation, probe=item.identifier, score=row["score"], scroll_repl_calls=row["scroll_repl_calls"])
    return row


def run(experiment_path: Path, *, chats_root: Path, scroll_source: Path, runtime_root: Path, output_path: Path, credential_home: Path, pilot: bool, probe_workers: int, judge_timeout_seconds: int, accept_runner_sha: str | None = None) -> dict[str, Any]:
    experiment = _read_json(experiment_path, "Codex BEAM 10M experiment manifest")
    _validate_experiment(experiment)
    execution_runner_sha = _sha256(Path(__file__))
    runner_sha, runner_override = _runner_lineage(experiment, execution_runner_sha, accept_runner_sha)
    if _sha256(_REPOSITORY_ROOT / "evals" / "scroll" / "beam.py") != experiment["beam_adapter_sha256"]:
        raise live.LiveRunError("Codex BEAM 10M execution code does not match its manifest")
    if not _JUDGE_TIMEOUT_MIN_SECONDS <= judge_timeout_seconds <= _JUDGE_TIMEOUT_MAX_SECONDS or not 1 <= probe_workers <= 8:
        raise live.LiveRunError("Codex BEAM 10M worker or judge timeout is invalid")
    if not credential_home.is_dir():
        raise live.LiveRunError("Codex BEAM 10M credential home is unavailable")
    live._require_chatgpt_codex_oauth(credential_home)
    for conversation, expected in experiment["conversation_sha256"].items():
        if _sha256(chats_root / "10M" / conversation / "chat.json") != expected:
            raise live.LiveRunError(f"Codex BEAM 10M conversation hash does not match: {conversation}")
    scroll_commit = live._git_output(["git", "-C", str(scroll_source), "rev-parse", "HEAD"], "could not verify pinned Scroll source revision")
    if scroll_commit != experiment["source_revisions"].get("scroll"):
        raise live.LiveRunError("Codex BEAM 10M Scroll source revision does not match")
    live._require_clean_git_checkout(scroll_source, "pinned Scroll source", allow_untracked=False)
    source_python = scroll_source / ".venv" / "bin" / "python"
    if not source_python.is_file():
        raise live.LiveRunError("Codex BEAM 10M judge environment is unavailable")
    all_items = beam._items(chats_root, experiment["conversations"])
    items = [item for item in all_items if not pilot or item.identifier in experiment["pilot_item_ids"]]
    if pilot and len(items) != len(experiment["pilot_item_ids"]):
        raise live.LiveRunError("Codex BEAM 10M pilot item is absent")
    selected_conversations = [conversation for conversation in experiment["conversations"] if any(beam._conversation_from_identifier(item.identifier) == conversation for item in items)]
    digest = _canonical_sha256(experiment)
    runtime_root = runtime_root.resolve()
    live._secure_directory(runtime_root)
    live._secure_directory(runtime_root / "seeds")
    live._secure_directory(runtime_root / "jobs")
    _progress("run", "started", arms=list(_ARMS), pilot=pilot, conversations=selected_conversations, probes=len(items), probe_workers=probe_workers, resumable=True)
    seeds = {conversation: _prepare_seed(conversation, experiment, digest, chats_root, runtime_root, credential_home, runner_sha, execution_runner_sha) for conversation in selected_conversations}
    judge_lineage = _judge_lineage(experiment, scroll_commit, judge_timeout_seconds)
    jobs = [(arm, item) for item in items for arm in _ARMS]
    rows_by_job: dict[tuple[str, str], dict[str, Any]] = {}
    failures: list[tuple[str, str]] = []
    def collect(job: tuple[str, live.EvaluationItem]) -> None:
        arm, item = job
        try:
            rows_by_job[(arm, item.identifier)] = _run_item(arm, item, experiment, digest, chats_root, scroll_source, source_python, runtime_root, credential_home, seeds, runner_sha, execution_runner_sha, judge_lineage)
        except Exception:
            failures.append((arm, item.identifier))
            _progress("probe", "failed", arm=arm, conversation=beam._conversation_from_identifier(item.identifier), probe=item.identifier)
    if probe_workers == 1:
        for job in jobs:
            collect(job)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=probe_workers) as executor:
            futures = {executor.submit(_run_item, arm, item, experiment, digest, chats_root, scroll_source, source_python, runtime_root, credential_home, seeds, runner_sha, execution_runner_sha, judge_lineage): (arm, item) for arm, item in jobs}
            for future in concurrent.futures.as_completed(futures):
                arm, item = futures[future]
                try:
                    rows_by_job[(arm, item.identifier)] = future.result()
                except Exception:
                    failures.append((arm, item.identifier))
                    _progress("probe", "failed", arm=arm, conversation=beam._conversation_from_identifier(item.identifier), probe=item.identifier)
    if failures:
        raise live.LiveRunError("Codex BEAM 10M probes failed after draining the queue: " + ", ".join(f"{arm}:{identifier}" for arm, identifier in failures))
    rows = [rows_by_job[(arm, item.identifier)] for arm, item in jobs]
    calls = {arm: [row["scroll_repl_calls"] for row in rows if row["provenance"]["arm"] == arm] for arm in _ARMS}
    report = {"schema_version": 1, "experiment": experiment["experiment"], "experiment_manifest_sha256": digest, "runner_sha256": runner_sha, "execution_runner_sha256": execution_runner_sha, "runner_override": runner_override, "provider": experiment["provider"], "authentication_mode": experiment["authentication_mode"], "billing_mode": experiment["billing_mode"], "agent_model": experiment["agent_model"], "judge_model": experiment["judge_model"], "reasoning_config": experiment["reasoning_config"], "judge_lineage": judge_lineage, "pilot": pilot, "conversations": selected_conversations, "arms": list(_ARMS), "probe_workers": probe_workers, "rows": rows, "score_totals": {arm: sum(row["score"] for row in rows if row["provenance"]["arm"] == arm) for arm in _ARMS}, "tool_adoption": {arm: {"items": len(calls[arm]), "items_with_scroll_repl": sum(value > 0 for value in calls[arm]), "scroll_repl_calls": sum(calls[arm])} for arm in _ARMS}, "baseline_seeds": {conversation: {**{key: seed[1]["metadata"][key] for key in ("raw_rows", "retained_rows", "summary_rows", "raw_tail_rows", "boundary_count")}, "seed_sha256": _sha256(seed[0])} for conversation, seed in seeds.items()}}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _progress("run", "completed", arms=list(_ARMS), pilot=pilot, rows=len(rows), output=str(output_path), score_totals=report["score_totals"])
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--seed-worker", type=Path)
    parser.add_argument("--experiment", type=Path)
    parser.add_argument("--beam-chats", type=Path)
    parser.add_argument("--scroll-source", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--credential-home", type=Path, default=Path.home() / ".hermes")
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--probe-workers", type=int, default=1)
    parser.add_argument("--judge-timeout-seconds", type=int, default=900)
    parser.add_argument("--accept-runner-sha")
    args = parser.parse_args()
    if args.worker:
        _worker(args.worker)
        return
    if args.seed_worker:
        _seed_worker(args.seed_worker)
        return
    if not all((args.experiment, args.beam_chats, args.scroll_source, args.runtime_root, args.output)):
        parser.error("--experiment, --beam-chats, --scroll-source, --runtime-root, and --output are required")
    report = run(args.experiment, chats_root=args.beam_chats, scroll_source=args.scroll_source, runtime_root=args.runtime_root, output_path=args.output, credential_home=args.credential_home, pilot=args.pilot, probe_workers=args.probe_workers, judge_timeout_seconds=args.judge_timeout_seconds, accept_runner_sha=args.accept_runner_sha)
    print(json.dumps({"arms": report["arms"], "rows": len(report["rows"]), "score_totals": report["score_totals"]}, sort_keys=True))


if __name__ == "__main__":
    main()
