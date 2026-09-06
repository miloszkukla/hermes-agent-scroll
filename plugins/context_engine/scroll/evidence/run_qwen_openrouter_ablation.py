"""Run a resumable Qwen/OpenRouter Scroll ablation sequence without modifying Hermes."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Mapping

_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from evals.scroll import hermes_live as live
from evals.scroll.live_manifest import validate_live_manifest
from plugins.context_engine.scroll.evidence import run_scroll_controller_retrieval_experiment as controller
from plugins.context_engine.scroll.evidence import run_scroll_tool_policy_experiment as policy


_REPRODUCTION_ARMS = ("stock", "scroll-advisory", "scroll-policy", "scroll-provider-forced", "scroll-controller")
_REPRODUCTION_PHASES = (("stock", "scroll-advisory"), ("scroll-policy",), ("scroll-provider-forced",), ("scroll-controller",))
_COST_POLICY_ARMS = ("stock", "scroll-policy")
_COST_POLICY_PHASES = (_COST_POLICY_ARMS,)
_SUPPORTED_ARMS = frozenset(_REPRODUCTION_ARMS)
_FORCED_TOOL_CHOICE = {"type": "function", "function": {"name": "scroll_repl"}}
_JUDGE_PROGRAM = live._JUDGE_PROGRAM.replace('"openai-codex"', '"openrouter"').replace('api_mode="codex_responses"', 'api_mode="chat_completions"').replace("ChatGPT Codex OAuth judge client", "OpenRouter judge client").replace('max_tokens=payload["max_output_tokens"])', 'max_tokens=payload["max_output_tokens"], service_tier=payload["requested_service_tier"], extra_body={"reasoning": payload["reasoning_config"]})').replace('lock = threading.Lock()\n', 'lock = threading.Lock()\nraw_usage = None\n').replace('        with lock:\n', '        global raw_usage\n        raw_usage = reply.usage.model_dump() if hasattr(reply.usage, "model_dump") else dict(reply.usage)\n        with lock:\n').replace('{"score": score, "usage": usage}', '{"score": score, "usage": usage, "raw_usage": raw_usage}')


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise live.LiveRunError(f"{label} is unavailable") from exc
    if not isinstance(value, dict):
        raise live.LiveRunError(f"{label} must be an object")
    return value


def _experiment_arms(experiment: Mapping[str, Any]) -> tuple[str, ...]:
    if experiment["experiment"] == "qwen-openrouter-scroll-ablation":
        return _REPRODUCTION_ARMS
    return _COST_POLICY_ARMS


def _experiment_phases(experiment: Mapping[str, Any]) -> tuple[tuple[str, ...], ...]:
    if experiment["experiment"] == "qwen-openrouter-scroll-ablation":
        return _REPRODUCTION_PHASES
    return _COST_POLICY_PHASES


def _validate_experiment(experiment: Mapping[str, Any]) -> None:
    required = {"schema_version", "experiment", "implementation_commit", "base_memory_manifest_sha256", "agent_prompt_sha256", "policy_prompt_sha256", "controller_prompt_sha256", "provider", "authentication_mode", "billing_mode", "api_mode", "agent_model", "judge_model", "routing_variant", "requested_service_tier", "reasoning_config", "temperature", "seed", "context_window_tokens", "max_iterations", "max_output_tokens", "max_parallel_workers", "input_token_budget", "output_token_budget", "cache_read_token_budget", "worker_timeout_seconds", "source_revisions", "selected_item_ids"}
    if set(experiment) != required or experiment["schema_version"] != 1 or experiment["experiment"] not in {"qwen-openrouter-scroll-ablation", "qwen-openrouter-cost-policy"}:
        raise live.LiveRunError("Qwen ablation manifest has an unexpected shape")
    if experiment["provider"] != "openrouter" or experiment["authentication_mode"] != "openrouter-api-key" or experiment["billing_mode"] != "openrouter-payg" or experiment["api_mode"] != "chat_completions" or experiment["routing_variant"] != "default":
        raise live.LiveRunError("Qwen ablation manifest does not pin the OpenRouter default route")
    if experiment["experiment"] == "qwen-openrouter-scroll-ablation":
        if experiment["agent_model"] != "qwen/qwen3.8-max" or experiment["judge_model"] != experiment["agent_model"]:
            raise live.LiveRunError("Qwen reproduction must use the paper's Qwen3.8-Max model for agent and judge")
        if experiment["requested_service_tier"] != "flex" or experiment["reasoning_config"] != {"enabled": True, "effort": "high"}:
            raise live.LiveRunError("Qwen reproduction must request OpenRouter Flex with high reasoning")
    elif experiment["agent_model"] != "qwen/qwen3.8-flash" or experiment["judge_model"] != experiment["agent_model"] or experiment["requested_service_tier"] != "flex" or experiment["reasoning_config"] != {"enabled": True, "effort": "high"}:
        raise live.LiveRunError("Qwen cost-policy experiment must differ only in the Qwen3.8-Flash model")
    if experiment["agent_prompt_sha256"] != hashlib.sha256(live.AGENT_SYSTEM_PROMPT.encode()).hexdigest() or experiment["policy_prompt_sha256"] != hashlib.sha256(policy.POLICY_PROMPT.encode()).hexdigest() or experiment["controller_prompt_sha256"] != hashlib.sha256(controller.CONTROLLER_PROMPT.encode()).hexdigest():
        raise live.LiveRunError("Qwen ablation prompt binding does not match")
    items = experiment["selected_item_ids"]
    if not isinstance(items, list) or len(items) != 10 or len(set(items)) != 10 or not all(isinstance(item, str) and item for item in items):
        raise live.LiveRunError("Qwen ablation requires ten unique item ids")
    numeric = ("seed", "context_window_tokens", "max_iterations", "max_output_tokens", "max_parallel_workers", "input_token_budget", "output_token_budget", "cache_read_token_budget", "worker_timeout_seconds")
    if any(not isinstance(experiment[field], int) or isinstance(experiment[field], bool) or experiment[field] <= 0 for field in numeric):
        raise live.LiveRunError("Qwen ablation has invalid numeric bounds")
    if experiment["max_parallel_workers"] > 4 or experiment["worker_timeout_seconds"] < 900 or experiment["temperature"] != 0:
        raise live.LiveRunError("Qwen ablation must retain deterministic concurrency and timeout bounds")
    if not isinstance(experiment["source_revisions"], dict) or not all(isinstance(key, str) and key and isinstance(value, str) and value for key, value in experiment["source_revisions"].items()):
        raise live.LiveRunError("Qwen ablation source revisions are invalid")


def _openrouter_api_key(credential_home: Path) -> str:
    value = os.getenv("OPENROUTER_API_KEY", "").strip()
    if value:
        return value
    try:
        lines = (credential_home / ".env").read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise live.LiveRunError("OpenRouter credential file is unavailable") from exc
    for line in lines:
        if line.startswith("OPENROUTER_API_KEY="):
            value = line.partition("=")[2].strip().strip("\"'")
            if value:
                return value
    raise live.LiveRunError("OPENROUTER_API_KEY is unavailable")


def _worker_config(job: Mapping[str, Any]) -> str:
    return (
        "model:\n"
        f"  context_length: {job['context_window']}\n"
        "context:\n"
        f"  engine: {'scroll' if job['arm'] != 'stock' else 'compressor'}\n"
        "compression:\n"
        "  enabled: true\n"
        "  threshold: 0.75\n"
        "auxiliary:\n"
        "  compression:\n"
        "    provider: openrouter\n"
        f"    model: {job['model']}\n"
        "    api_mode: chat_completions\n"
        f"    reasoning_effort: {job['reasoning_config']['effort']}\n"
        "    timeout: 300\n"
        f"    max_output_tokens: {job['max_output_tokens']}\n"
    )


def _build_agent(factory: Any, job: Mapping[str, Any], session_id: str, db: Any, toolsets: list[str], request_overrides: Mapping[str, Any]) -> Any:
    return factory(
        provider="openrouter", api_key=job["api_key"], base_url="https://openrouter.ai/api/v1", api_mode="chat_completions", model=job["model"], session_id=session_id, session_db=db,
        enabled_toolsets=toolsets, quiet_mode=True, skip_context_files=True, skip_memory=True, skip_background_review=True, platform="cli", max_iterations=int(job["max_iterations"]),
        max_tokens=int(job["max_output_tokens"]), reasoning_config=dict(job["reasoning_config"]), request_overrides=dict(request_overrides), fallback_model=[],
    )


def _auxiliary_usage(db: Any, session_id: str, expected_model: str) -> tuple[int, int, int]:
    try:
        with db._read_ctx() as connection:
            rows = connection.execute("SELECT COALESCE(input_tokens, 0), COALESCE(output_tokens, 0), COALESCE(cache_read_tokens, 0), model, billing_provider FROM session_model_usage WHERE session_id = ? AND task <> ''", (session_id,)).fetchall()
        if any(row[3] != expected_model or row[4] not in {"", "openrouter"} for row in rows):
            raise live.LiveRunError("Qwen ablation auxiliary usage left OpenRouter")
        return tuple(sum(int(row[index] or 0) for row in rows) for index in range(3))
    except Exception as exc:
        if isinstance(exc, live.LiveRunError):
            raise
        raise live.LiveRunError("Qwen ablation auxiliary usage is unavailable") from exc


def _worker(job_path: Path) -> None:
    job = live._read_json(job_path)
    api_key = job.get("api_key")
    if not isinstance(api_key, str) or not api_key.strip():
        raise live.LiveRunError("Qwen worker access key is unavailable")
    try:
        job_path.unlink()
    except OSError as exc:
        raise live.LiveRunError("Qwen worker access key could not be removed") from exc
    if job.get("arm") not in _SUPPORTED_ARMS:
        raise live.LiveRunError("Qwen worker arm is invalid")
    runtime_home = Path(job["runtime_home"])
    runtime_home.mkdir(parents=True, exist_ok=True)
    (runtime_home / "config.yaml").write_text(_worker_config(job), encoding="utf-8")
    os.environ["HERMES_HOME"] = str(runtime_home)
    os.environ["OPENROUTER_API_KEY"] = api_key
    from hermes_state import SessionDB
    from run_agent import AIAgent
    from agent.aux_accounting import reset_accounting_context, set_accounting_context

    db = SessionDB(runtime_home / "state.db")
    session_id = f"qwen-scroll-eval-{uuid.uuid4().hex}"
    db.create_session(session_id, source="eval", model=job["model"])
    db.append_messages_batch(session_id, job["history"], chunk_rows=256)
    history = db.get_messages_as_conversation(session_id, repair_alternation=True, include_row_ids=True)
    accounting_failures = []
    accounting_token = set_accounting_context(db, session_id, failure_sink=accounting_failures)
    agent = None
    try:
        request_overrides = {"temperature": job["temperature"], "seed": job["seed"], "service_tier": job["requested_service_tier"]}
        if job["arm"] == "scroll-provider-forced":
            request_overrides["tool_choice"] = _FORCED_TOOL_CHOICE
        toolsets = [] if job["arm"] == "stock" else ["context_engine"]
        agent = _build_agent(AIAgent, job, session_id, db, toolsets, request_overrides)
        if getattr(agent, "provider", None) != "openrouter" or getattr(agent, "api_mode", None) != "chat_completions" or getattr(agent, "model", None) != job["model"]:
            raise live.LiveRunError("Qwen worker left the frozen OpenRouter route")
        system_message = live.AGENT_SYSTEM_PROMPT
        user_message = job["probe"]["question"]
        mode_data: dict[str, Any] = {}
        if job["arm"] == "scroll-policy":
            system_message = policy.POLICY_PROMPT
        elif job["arm"] == "scroll-provider-forced":
            engine = getattr(agent, "context_compressor", None)
            original = getattr(engine, "handle_tool_call", None)
            if not callable(original):
                raise live.LiveRunError("provider-forced Qwen arm has no Scroll REPL")
            force_state = {"released": False}
            def release_after_first_scroll(name: str, args: dict[str, Any], **kwargs: Any) -> str:
                result = original(name, args, **kwargs)
                if name == "scroll_repl" and not force_state["released"]:
                    overrides = dict(agent.request_overrides)
                    if overrides.pop("tool_choice", None) != _FORCED_TOOL_CHOICE:
                        raise live.LiveRunError("provider-forced Qwen arm lost its required tool choice")
                    agent.request_overrides = overrides
                    force_state["released"] = True
                return result
            engine.handle_tool_call = release_after_first_scroll
            mode_data = force_state
        elif job["arm"] == "scroll-controller":
            engine = getattr(agent, "context_compressor", None)
            retrieve = getattr(engine, "handle_tool_call", None)
            if not callable(retrieve):
                raise live.LiveRunError("controller Qwen arm has no Scroll REPL")
            query = controller._controller_query(user_message)
            source = controller._controller_source(query)
            try:
                retrieved_result = json.loads(retrieve("scroll_repl", {"source": source}))
            except (TypeError, json.JSONDecodeError) as exc:
                raise live.LiveRunError("controller Qwen Scroll result is malformed") from exc
            retrieved = retrieved_result.get("stdout") if isinstance(retrieved_result, dict) else None
            if not isinstance(retrieved, str) or "error" in retrieved_result:
                raise live.LiveRunError("controller Qwen Scroll read failed")
            user_message = controller._controller_user_message(user_message, retrieved)
            system_message = controller.CONTROLLER_PROMPT
            mode_data = {"query_sha256": hashlib.sha256(query.encode()).hexdigest(), "source_sha256": hashlib.sha256(source.encode()).hexdigest(), "retrieval_sha256": hashlib.sha256(retrieved.encode()).hexdigest()}
        response = agent.run_conversation(user_message, system_message=system_message, conversation_history=history)
        answer = response.get("final_response") if isinstance(response, dict) else None
        if not isinstance(answer, str) or not answer.strip() or (isinstance(response, dict) and response.get("failed")):
            raise live.LiveRunError("Qwen arm failed before a final answer")
        if int(getattr(agent, "session_api_calls", 0) or 0) <= 0 or int(getattr(agent, "session_output_tokens", 0) or 0) <= 0:
            raise live.LiveRunError("Qwen arm omitted main-model usage")
        if accounting_failures:
            raise live.LiveRunError("Qwen auxiliary accounting failed")
        auxiliary_input, auxiliary_output, auxiliary_cache_read = _auxiliary_usage(db, session_id, job["model"])
        payload = live._worker_result_payload(answer, int(getattr(agent, "session_input_tokens", 0) or 0) + auxiliary_input, int(getattr(agent, "session_output_tokens", 0) or 0) + auxiliary_output, int(getattr(agent, "session_cache_read_tokens", 0) or 0) + auxiliary_cache_read, 0.0, job.get("result_provenance"))
        payload["mode_data"] = mode_data
        Path(job["result_path"]).write_text(json.dumps(payload), encoding="utf-8")
    finally:
        reset_accounting_context(accounting_token)
        if agent is not None:
            agent.close()
        db.close()


def _resume_row(path: Path, provenance: Mapping[str, str], arm: str) -> dict[str, Any] | None:
    try:
        row = _read_json(path, "Qwen ablation row")
    except live.LiveRunError:
        return None
    usage = row.get("usage")
    judge_usage = row.get("judge_usage")
    if row.get("provenance") != dict(provenance) or not isinstance(row.get("score"), (int, float)) or isinstance(row.get("score"), bool):
        return None
    if not isinstance(row.get("answer_sha256"), str) or len(row["answer_sha256"]) != 64 or not isinstance(usage, dict) or not isinstance(judge_usage, dict):
        return None
    fields = ("input_tokens", "output_tokens", "cache_read_tokens")
    if any(not isinstance(bucket.get(field), int) or isinstance(bucket.get(field), bool) or bucket[field] < 0 for bucket in (usage, judge_usage) for field in fields):
        return None
    mode_data = row.get("mode_data")
    if arm == "scroll-provider-forced" and mode_data != {"released": True}:
        return None
    if arm == "scroll-controller" and (not isinstance(mode_data, dict) or set(mode_data) != {"query_sha256", "source_sha256", "retrieval_sha256"} or any(not isinstance(value, str) or len(value) != 64 for value in mode_data.values())):
        return None
    if arm not in {"scroll-provider-forced", "scroll-controller"} and mode_data != {}:
        return None
    if not isinstance(row.get("model_scroll_repl_calls"), int) or row["model_scroll_repl_calls"] < 0:
        return None
    return row


def _tool_call_count(state_path: Path) -> int:
    try:
        import sqlite3
        with sqlite3.connect(state_path) as connection:
            return int(connection.execute("SELECT COUNT(*) FROM messages WHERE tool_name = ?", ("scroll_repl",)).fetchone()[0])
    except Exception as exc:
        raise live.LiveRunError("Qwen ablation could not read tool-call metadata") from exc


def _judge_item(item: Any, answer: str, experiment: Mapping[str, Any], source_python: Path, scroll_source: Path, api_key: str, judge_timeout_seconds: int = 600) -> dict[str, Any]:
    payload = {"benchmark": item.benchmark, "question_type": item.question_type, "gold": item.gold, "answer": answer, "model": experiment["judge_model"], "max_output_tokens": experiment["max_output_tokens"], "requested_service_tier": experiment["requested_service_tier"], "reasoning_config": experiment["reasoning_config"], "api_key": api_key}
    with tempfile.TemporaryDirectory(prefix="scroll-qwen-judge-") as judge_home:
        judge_env = live._isolated_subprocess_environment()
        judge_env["HERMES_HOME"] = judge_home
        judge_env["OPENROUTER_API_KEY"] = api_key
        try:
            process = subprocess.run([str(source_python), "-c", _JUDGE_PROGRAM], input=json.dumps(payload), text=True, cwd=scroll_source, env=judge_env, capture_output=True, check=True, timeout=judge_timeout_seconds)
            judge_failure = next((line for line in process.stdout.splitlines() if line.startswith("[longmemeval.judge] judge call failed")), "")
            if judge_failure:
                raise live.LiveRunError(f"pinned {item.benchmark} Qwen judge invocation failed: {judge_failure.replace(api_key, '[redacted]')[-500:]}")
            result = next((json.loads(line) for line in reversed(process.stdout.splitlines()) if '"raw_usage"' in line), None)
            if not isinstance(result, dict):
                raise live.LiveRunError(f"pinned {item.benchmark} Qwen judge omitted its tagged result")
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "").replace(api_key, "[redacted]").strip().splitlines()
            raise live.LiveRunError(f"pinned {item.benchmark} Qwen judge failed: {detail[-1] if detail else 'no stderr'}") from None
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            raise live.LiveRunError(f"pinned {item.benchmark} Qwen judge failed") from exc
    usage = result.get("usage") if isinstance(result, dict) else None
    if not isinstance(result, dict) or not isinstance(result.get("score"), (int, float)) or isinstance(result["score"], bool) or not isinstance(usage, dict):
        raise live.LiveRunError(f"pinned {item.benchmark} Qwen judge returned an invalid result")
    fields = ("input_tokens", "output_tokens", "cache_read_tokens")
    if any(not isinstance(usage.get(field), int) or isinstance(usage.get(field), bool) for field in fields) or usage["input_tokens"] < 0 or usage["output_tokens"] <= 0 or usage["cache_read_tokens"] < 0 or usage["input_tokens"] + usage["cache_read_tokens"] <= 0:
        raise live.LiveRunError(f"pinned {item.benchmark} Qwen judge returned invalid usage: {usage}; raw usage: {result.get('raw_usage')}")
    return {"score": float(result["score"]), "usage": {field: usage[field] for field in fields}}


def _run_item(item: Any, arm: str, *, base: Mapping[str, Any], experiment: Mapping[str, Any], experiment_digest: str, source_python: Path, scroll_source: Path, runtime_root: Path, credential_home: Path, resume: bool) -> dict[str, Any]:
    job_root = runtime_root / "jobs" / hashlib.sha256(f"{experiment_digest}:{arm}:{item.identifier}".encode()).hexdigest()
    live._secure_directory(job_root)
    result_path = job_root / "result.json"
    row_path = job_root / "row.json"
    provenance = {"experiment_manifest_sha256": experiment_digest, "implementation_commit": str(base["implementation_commit"]), "arm": arm, "identifier": item.identifier, "model": str(experiment["agent_model"]), "history_sha256": hashlib.sha256(json.dumps(item.history, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "probe_sha256": hashlib.sha256(json.dumps(item.public_probe, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
    if resume and (row := _resume_row(row_path, provenance, arm)) is not None:
        return row
    result = live._resumable_worker_result(result_path, provenance) if resume and result_path.is_file() else None
    if result is None:
        job_path = job_root / "job.json"
        live._write_private_json(job_path, {"arm": arm, "model": experiment["agent_model"], "context_window": experiment["context_window_tokens"], "max_iterations": experiment["max_iterations"], "temperature": experiment["temperature"], "seed": experiment["seed"], "max_output_tokens": experiment["max_output_tokens"], "reasoning_config": experiment["reasoning_config"], "requested_service_tier": experiment["requested_service_tier"], "history": item.history, "probe": item.public_probe, "runtime_home": str(job_root / "home"), "api_key": _openrouter_api_key(credential_home), "result_path": str(result_path), "result_provenance": provenance})
        try:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", str(job_path)], cwd=_REPOSITORY_ROOT, env=live._isolated_subprocess_environment(), check=True, capture_output=True, text=True, timeout=experiment["worker_timeout_seconds"])
            result = _read_json(result_path, "Qwen worker result")
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "").replace(_openrouter_api_key(credential_home), "[redacted]").strip().splitlines()
            raise live.LiveRunError(f"Qwen {arm} arm failed for {item.identifier}: {detail[-1] if detail else 'no stderr'}") from None
        except (OSError, subprocess.SubprocessError, live.LiveRunError) as exc:
            raise live.LiveRunError(f"Qwen {arm} arm failed for {item.identifier}") from exc
        finally:
            job_path.unlink(missing_ok=True)
    if not isinstance(result.get("answer"), str) or not result["answer"].strip() or not isinstance(result.get("usage"), dict):
        raise live.LiveRunError(f"Qwen {arm} arm returned an invalid result for {item.identifier}")
    mode_data = result.get("mode_data")
    if arm == "scroll-provider-forced" and mode_data != {"released": True}:
        raise live.LiveRunError(f"Qwen {arm} arm did not release its one-shot tool choice")
    if arm == "scroll-controller" and (not isinstance(mode_data, dict) or set(mode_data) != {"query_sha256", "source_sha256", "retrieval_sha256"}):
        raise live.LiveRunError(f"Qwen {arm} arm omitted controller provenance")
    if arm not in {"scroll-provider-forced", "scroll-controller"} and mode_data != {}:
        raise live.LiveRunError(f"Qwen {arm} arm returned unexpected mode metadata")
    verdict = _judge_item(item, result["answer"], experiment, source_python, scroll_source, _openrouter_api_key(credential_home))
    row = {"task_id": item.identifier, "arm": arm, "score": float(verdict["score"]), "answer_sha256": hashlib.sha256(result["answer"].encode()).hexdigest(), "usage": result["usage"], "judge_usage": verdict["usage"], "mode_data": mode_data, "model_scroll_repl_calls": _tool_call_count(job_root / "home" / "state.db"), "provenance": provenance}
    live._write_private_json(row_path, row)
    return row


def run(experiment_path: Path, base_manifest_path: Path, *, longmemeval_path: Path, beam_chats_root: Path, scroll_source: Path, runtime_root: Path, output_path: Path, credential_home: Path, resume: bool, stop_after_phase: int | None, only_arm: str | None) -> dict[str, Any]:
    experiment = _read_json(experiment_path, "Qwen ablation manifest")
    _validate_experiment(experiment)
    base = _read_json(base_manifest_path, "base memory manifest")
    validate_live_manifest(base)
    live.verify_manifest_provenance(base, _REPOSITORY_ROOT)
    if _canonical_sha256(base) != experiment["base_memory_manifest_sha256"] or base["implementation_commit"] != experiment["implementation_commit"] or base["source_revisions"] != experiment["source_revisions"]:
        raise live.LiveRunError("Qwen ablation does not match its frozen source manifest")
    source_commit = live._git_output(["git", "-C", str(scroll_source), "rev-parse", "HEAD"], "could not verify pinned Scroll source revision")
    if source_commit != experiment["source_revisions"]["scroll"]:
        raise live.LiveRunError("Qwen ablation Scroll source revision does not match")
    live._require_clean_git_checkout(scroll_source, "pinned Scroll source", allow_untracked=False)
    source_python = scroll_source / ".venv" / "bin" / "python"
    if not source_python.is_file():
        raise live.LiveRunError("Qwen ablation judge environment is unavailable")
    _openrouter_api_key(credential_home)
    live.verify_memory_inputs(base, longmemeval_path, beam_chats_root)
    all_items = {item.identifier: item for item in live.load_manifest_items(base, longmemeval_path=longmemeval_path, beam_chats_root=beam_chats_root)}
    try:
        items = [all_items[item_id] for item_id in experiment["selected_item_ids"]]
    except KeyError as exc:
        raise live.LiveRunError("Qwen ablation item is not in the frozen source manifest") from exc
    runtime_root = runtime_root.resolve()
    live._secure_directory(runtime_root)
    live._secure_directory(runtime_root / "jobs")
    arms = _experiment_arms(experiment)
    phases = _experiment_phases(experiment)
    if only_arm is not None:
        if only_arm not in arms:
            raise live.LiveRunError(f"Arm {only_arm!r} is not enabled for {experiment['experiment']}")
        arms = (only_arm,)
        phases = (arms,)
    if stop_after_phase is not None and not 1 <= stop_after_phase <= len(phases):
        raise live.LiveRunError(f"--stop-after-phase must be between 1 and {len(phases)}")
    experiment_digest = _canonical_sha256(experiment)
    rows = []
    completed_phases = 0
    for phase_index, phase in enumerate(phases, start=1):
        jobs = [(item, arm) for arm in phase for item in items]
        with concurrent.futures.ThreadPoolExecutor(max_workers=experiment["max_parallel_workers"]) as executor:
            rows.extend(executor.map(lambda job: _run_item(job[0], job[1], base=base, experiment=experiment, experiment_digest=experiment_digest, source_python=source_python, scroll_source=scroll_source, runtime_root=runtime_root, credential_home=credential_home, resume=resume), jobs))
        completed_phases = phase_index
        if stop_after_phase == phase_index:
            break
    order = {(arm, item.identifier): index for index, (arm, item) in enumerate((arm, item) for arm in arms for item in items)}
    rows.sort(key=lambda row: order[(row["arm"], row["task_id"])])
    calls = {arm: [row["model_scroll_repl_calls"] for row in rows if row["arm"] == arm] for arm in arms}
    report = {"schema_version": 1, "experiment": experiment["experiment"], "experiment_manifest_sha256": experiment_digest, "base_memory_manifest_sha256": experiment["base_memory_manifest_sha256"], "implementation_commit": base["implementation_commit"], "provider": experiment["provider"], "api_mode": experiment["api_mode"], "agent_model": experiment["agent_model"], "judge_model": experiment["judge_model"], "routing_variant": experiment["routing_variant"], "requested_service_tier": experiment["requested_service_tier"], "reasoning_config": experiment["reasoning_config"], "completed_phases": completed_phases, "complete": only_arm is None and completed_phases == len(phases), "selected_arm": only_arm, "rows": rows, "tool_adoption": {arm: {"items": len(calls[arm]), "items_with_scroll_repl": sum(call > 0 for call in calls[arm]), "scroll_repl_calls": sum(calls[arm])} for arm in arms}, "controller_retrieval": {"items": len(items) if "scroll-controller" in arms else 0, "scroll_repl_calls": len(items) if "scroll-controller" in arms else 0}, "score_totals": {arm: sum(row["score"] for row in rows if row["arm"] == arm) for arm in arms}}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--experiment", type=Path)
    parser.add_argument("--base-manifest", type=Path)
    parser.add_argument("--longmemeval", type=Path)
    parser.add_argument("--beam-chats", type=Path)
    parser.add_argument("--scroll-source", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--credential-home", type=Path, default=Path.home() / ".hermes")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stop-after-phase", type=int)
    parser.add_argument("--only-arm", choices=_SUPPORTED_ARMS)
    args = parser.parse_args()
    if args.worker:
        _worker(args.worker)
        return
    required = (args.experiment, args.base_manifest, args.longmemeval, args.beam_chats, args.scroll_source, args.runtime_root, args.output)
    if not all(required):
        parser.error("--experiment, --base-manifest, --longmemeval, --beam-chats, --scroll-source, --runtime-root, and --output are required")
    report = run(args.experiment, args.base_manifest, longmemeval_path=args.longmemeval, beam_chats_root=args.beam_chats, scroll_source=args.scroll_source, runtime_root=args.runtime_root, output_path=args.output, credential_home=args.credential_home, resume=args.resume, stop_after_phase=args.stop_after_phase, only_arm=args.only_arm)
    print(json.dumps({"rows": len(report["rows"]), "score_totals": report["score_totals"], "tool_adoption": report["tool_adoption"]}, sort_keys=True))


if __name__ == "__main__":
    main()
