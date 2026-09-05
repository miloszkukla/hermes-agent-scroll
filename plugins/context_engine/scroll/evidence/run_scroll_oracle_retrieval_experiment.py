"""Run a resumable gold-conditioned Scroll retrieval diagnostic without modifying Hermes."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Mapping

_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from evals.scroll import hermes_live as live
from evals.scroll.live_manifest import validate_live_manifest
from plugins.context_engine.scroll.evidence import run_scroll_controller_retrieval_experiment as controller


_QUERY_WORDS = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_QUERY_STOPWORDS = controller._QUERY_STOPWORDS
_ORACLE_HINT_FIELDS = ("answer", "ideal_answer", "ideal_response")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    return controller._read_json(path, label)


def _answer_hint(gold: Mapping[str, Any]) -> str:
    values = [str(gold[field]).strip() for field in _ORACLE_HINT_FIELDS if gold.get(field) is not None and str(gold[field]).strip()]
    if not values:
        raise live.LiveRunError("oracle-retrieval item has no answer-bearing gold field")
    return " ".join(values)


def _terms(value: str, *, retain_short: bool) -> list[str]:
    result = []
    for raw in _QUERY_WORDS.findall(value.casefold()):
        if raw in _QUERY_STOPWORDS or (not retain_short and len(raw) < 3) or raw in result:
            continue
        result.append(raw)
    return result


def _oracle_query(question: str, hint: str) -> str:
    terms = []
    for term in [*_terms(hint, retain_short=True), *_terms(question, retain_short=False)]:
        if term not in terms:
            terms.append(term)
        if len(terms) == 8:
            break
    return " OR ".join(terms) or "history"


def _validate_experiment(experiment: Mapping[str, Any]) -> None:
    required = {"schema_version", "experiment", "implementation_commit", "base_memory_manifest_sha256", "base_memory_report_sha256", "policy_report_sha256", "controller_report_sha256", "controller_prompt_sha256", "oracle_query_algorithm", "controller_retrieval_algorithm", "agent_model", "judge_model", "source_revisions", "max_parallel_workers", "worker_timeout_seconds", "selected_item_ids"}
    if set(experiment) != required or experiment["schema_version"] != 1 or experiment["experiment"] != "scroll-oracle-retrieval":
        raise live.LiveRunError("oracle-retrieval experiment manifest has an unexpected shape")
    items = experiment["selected_item_ids"]
    if not isinstance(items, list) or len(items) != 10 or len(set(items)) != 10 or not all(isinstance(item, str) and item for item in items):
        raise live.LiveRunError("oracle-retrieval experiment requires ten unique item ids")
    if not isinstance(experiment["max_parallel_workers"], int) or not 1 <= experiment["max_parallel_workers"] <= 4:
        raise live.LiveRunError("oracle-retrieval experiment has an invalid worker count")
    if not isinstance(experiment["worker_timeout_seconds"], int) or experiment["worker_timeout_seconds"] < 900:
        raise live.LiveRunError("oracle-retrieval experiment must retain the 900-second worker bound")
    if experiment["controller_prompt_sha256"] != hashlib.sha256(controller.CONTROLLER_PROMPT.encode()).hexdigest():
        raise live.LiveRunError("oracle-retrieval experiment prompt binding does not match")
    if experiment["oracle_query_algorithm"] != "gold_answer_terms_question_backfill_v1":
        raise live.LiveRunError("oracle-retrieval experiment query algorithm does not match")
    if experiment["controller_retrieval_algorithm"] != "search_snippets_v1":
        raise live.LiveRunError("oracle-retrieval experiment retrieval algorithm does not match")


def _worker(job_path: Path) -> None:
    job = live._read_json(job_path)
    api_key = job.get("api_key")
    if not isinstance(api_key, str) or not api_key.strip():
        raise live.LiveRunError("worker access-token lease is unavailable")
    try:
        job_path.unlink()
    except OSError as exc:
        raise live.LiveRunError("worker access-token lease could not be removed") from exc
    hint = job.get("oracle_hint")
    if not isinstance(hint, str) or not hint.strip():
        raise live.LiveRunError("oracle-retrieval hint is unavailable")
    runtime_home = Path(job["runtime_home"])
    runtime_home.mkdir(parents=True, exist_ok=True)
    (runtime_home / "config.yaml").write_text(live._worker_config(job), encoding="utf-8")
    os.environ["HERMES_HOME"] = str(runtime_home)
    from hermes_state import SessionDB
    from run_agent import AIAgent
    from agent.aux_accounting import reset_accounting_context, set_accounting_context

    db = SessionDB(runtime_home / "state.db")
    session_id = f"scroll-oracle-eval-{uuid.uuid4().hex}"
    db.create_session(session_id, source="eval", model=job["model"])
    db.append_messages_batch(session_id, job["history"], chunk_rows=256)
    history = db.get_messages_as_conversation(session_id, repair_alternation=True, include_row_ids=True)
    accounting_failures = []
    accounting_token = set_accounting_context(db, session_id, failure_sink=accounting_failures)
    agent = None
    try:
        agent = live._build_live_agent(AIAgent, job, session_id, db, ["context_engine"])
        if getattr(agent, "provider", None) != "openai-codex" or getattr(agent, "api_mode", None) != "codex_responses" or getattr(agent, "model", None) != job["model"]:
            raise live.LiveRunError("evaluation agent left the ChatGPT Codex OAuth route")
        retrieve = getattr(getattr(agent, "context_compressor", None), "handle_tool_call", None)
        if not callable(retrieve):
            raise live.LiveRunError("oracle-retrieval agent has no Scroll REPL")
        query = _oracle_query(job["probe"]["question"], hint)
        source = f"print(ms.search({json.dumps(query)}, k=3))"
        retrieved_payload = retrieve("scroll_repl", {"source": source})
        try:
            retrieved_result = json.loads(retrieved_payload)
        except (TypeError, json.JSONDecodeError) as exc:
            raise live.LiveRunError("oracle-retrieval Scroll result is malformed") from exc
        retrieved = retrieved_result.get("stdout") if isinstance(retrieved_result, dict) else None
        if not isinstance(retrieved, str) or "error" in retrieved_result:
            raise live.LiveRunError("oracle-retrieval Scroll read failed")
        response = agent.run_conversation(controller._controller_user_message(job["probe"]["question"], retrieved), system_message=controller.CONTROLLER_PROMPT, conversation_history=history)
        answer = response.get("final_response") if isinstance(response, dict) else None
        if not isinstance(answer, str) or not answer.strip() or (isinstance(response, dict) and response.get("failed")):
            raise live.LiveRunError("Hermes oracle-retrieval arm failed before a final answer")
        if int(getattr(agent, "session_api_calls", 0) or 0) <= 0 or int(getattr(agent, "session_output_tokens", 0) or 0) <= 0:
            raise live.LiveRunError("Hermes oracle-retrieval arm omitted main-model usage")
        if accounting_failures:
            raise live.LiveRunError("auxiliary evaluation accounting failed")
        auxiliary_input, auxiliary_output, auxiliary_cache_read = live._auxiliary_usage(db, session_id, job["model"])
        payload = live._worker_result_payload(answer, int(getattr(agent, "session_input_tokens", 0) or 0) + auxiliary_input, int(getattr(agent, "session_output_tokens", 0) or 0) + auxiliary_output, int(getattr(agent, "session_cache_read_tokens", 0) or 0) + auxiliary_cache_read, 0.0, job.get("result_provenance"))
        payload["controller"] = {"oracle_hint_sha256": hashlib.sha256(hint.encode()).hexdigest(), "query_sha256": hashlib.sha256(query.encode()).hexdigest(), "source_sha256": hashlib.sha256(source.encode()).hexdigest(), "retrieval_sha256": hashlib.sha256(retrieved.encode()).hexdigest()}
        Path(job["result_path"]).write_text(json.dumps(payload), encoding="utf-8")
    finally:
        reset_accounting_context(accounting_token)
        if agent is not None:
            agent.close()
        db.close()


def _resume_row(path: Path, provenance: Mapping[str, str]) -> dict[str, Any] | None:
    try:
        row = _read_json(path, "oracle-retrieval row")
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
    controller_data = row.get("controller")
    if not isinstance(controller_data, dict) or set(controller_data) != {"oracle_hint_sha256", "query_sha256", "source_sha256", "retrieval_sha256"} or any(not isinstance(value, str) or len(value) != 64 for value in controller_data.values()):
        return None
    if not isinstance(row.get("model_scroll_repl_calls"), int) or row["model_scroll_repl_calls"] < 0:
        return None
    return row


def _run_item(item: Any, *, base: Mapping[str, Any], experiment: Mapping[str, Any], experiment_digest: str, source_python: Path, scroll_source: Path, runtime_root: Path, credential_home: Path, resume: bool) -> dict[str, Any]:
    job_root = runtime_root / "jobs" / hashlib.sha256(f"{experiment_digest}:{item.identifier}".encode()).hexdigest()
    live._secure_directory(job_root)
    result_path = job_root / "result.json"
    row_path = job_root / "row.json"
    hint = _answer_hint(item.gold)
    provenance = {
        "experiment_manifest_sha256": experiment_digest, "implementation_commit": str(base["implementation_commit"]),
        "arm": "scroll-oracle", "identifier": item.identifier, "model": str(base["agent_model"]),
        "history_sha256": hashlib.sha256(json.dumps(item.history, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "probe_sha256": hashlib.sha256(json.dumps(item.public_probe, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "oracle_hint_sha256": hashlib.sha256(hint.encode()).hexdigest(),
    }
    if resume and (row := _resume_row(row_path, provenance)) is not None:
        return row
    result = live._resumable_worker_result(result_path, provenance) if resume and result_path.is_file() else None
    if result is None:
        job_path = job_root / "job.json"
        live._write_private_json(job_path, {
            "arm": "scroll", "model": base["agent_model"], "context_window": base["context_window_tokens"], "max_iterations": base["max_iterations"], "temperature": base["temperature"], "seed": base["seed"], "max_output_tokens": base["max_output_tokens"], "output_token_budget": base["output_token_budget"], "cache_read_token_budget": base["cache_read_token_budget"],
            "history": item.history, "probe": item.public_probe, "oracle_hint": hint, "runtime_home": str(job_root / "home"), "api_key": live._lease_chatgpt_codex_access_token(credential_home), "result_path": str(result_path), "result_provenance": provenance,
        })
        try:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", str(job_path)], cwd=_REPOSITORY_ROOT, env=live._isolated_subprocess_environment(), check=True, capture_output=True, text=True, timeout=experiment["worker_timeout_seconds"])
            result = _read_json(result_path, "oracle-retrieval worker result")
        except (OSError, subprocess.SubprocessError, live.LiveRunError) as exc:
            raise live.LiveRunError(f"oracle-retrieval worker failed for {item.identifier}") from exc
        finally:
            job_path.unlink(missing_ok=True)
    controller_data = result.get("controller")
    if not isinstance(result.get("answer"), str) or not result["answer"].strip() or not isinstance(result.get("usage"), dict) or not isinstance(controller_data, dict):
        raise live.LiveRunError(f"oracle-retrieval worker returned an invalid result for {item.identifier}")
    controller_public = {key: controller_data.get(key) for key in ("oracle_hint_sha256", "query_sha256", "source_sha256", "retrieval_sha256")}
    if any(not isinstance(value, str) or len(value) != 64 for value in controller_public.values()):
        raise live.LiveRunError(f"oracle-retrieval worker omitted controller provenance for {item.identifier}")
    verdict = live._judge_item(item, result["answer"], base, source_python, scroll_source, live._lease_chatgpt_codex_access_token(credential_home))
    row = {"task_id": item.identifier, "score": float(verdict["score"]), "answer_sha256": hashlib.sha256(result["answer"].encode()).hexdigest(), "usage": result["usage"], "judge_usage": verdict["usage"], "controller": controller_public, "model_scroll_repl_calls": controller._tool_call_count(job_root / "home" / "state.db"), "provenance": provenance}
    live._write_private_json(row_path, row)
    return row


def run(experiment_path: Path, base_manifest_path: Path, base_report_path: Path, policy_report_path: Path, controller_report_path: Path, *, longmemeval_path: Path, beam_chats_root: Path, scroll_source: Path, runtime_root: Path, output_path: Path, credential_home: Path, resume: bool) -> dict[str, Any]:
    experiment = _read_json(experiment_path, "oracle-retrieval experiment manifest")
    _validate_experiment(experiment)
    base = _read_json(base_manifest_path, "base memory manifest")
    validate_live_manifest(base)
    live.verify_manifest_provenance(base, _REPOSITORY_ROOT)
    if base["implementation_commit"] != experiment["implementation_commit"] or base["agent_model"] != experiment["agent_model"] or base["judge_model"] != experiment["judge_model"] or base["source_revisions"] != experiment["source_revisions"]:
        raise live.LiveRunError("oracle-retrieval experiment does not match its base manifest")
    if controller._canonical_sha256(base) != experiment["base_memory_manifest_sha256"] or controller._file_sha256(base_report_path) != experiment["base_memory_report_sha256"] or controller._file_sha256(policy_report_path) != experiment["policy_report_sha256"] or controller._file_sha256(controller_report_path) != experiment["controller_report_sha256"]:
        raise live.LiveRunError("oracle-retrieval experiment baseline binding does not match")
    policy_report = _read_json(policy_report_path, "policy baseline report")
    controller_report = _read_json(controller_report_path, "controller baseline report")
    if policy_report.get("base_memory_manifest_sha256") != experiment["base_memory_manifest_sha256"] or policy_report.get("base_memory_report_sha256") != experiment["base_memory_report_sha256"] or controller_report.get("base_memory_manifest_sha256") != experiment["base_memory_manifest_sha256"] or controller_report.get("base_memory_report_sha256") != experiment["base_memory_report_sha256"]:
        raise live.LiveRunError("oracle-retrieval comparison reports are not bound to the frozen baseline")
    source_commit = live._git_output(["git", "-C", str(scroll_source), "rev-parse", "HEAD"], "could not verify pinned Scroll source revision")
    if source_commit != base["source_revisions"]["scroll"]:
        raise live.LiveRunError("oracle-retrieval experiment Scroll source revision does not match")
    live._require_clean_git_checkout(scroll_source, "pinned Scroll source", allow_untracked=False)
    source_python = scroll_source / ".venv" / "bin" / "python"
    if not source_python.is_file():
        raise live.LiveRunError("oracle-retrieval experiment judge environment is unavailable")
    live._require_chatgpt_codex_oauth(credential_home)
    live.verify_memory_inputs(base, longmemeval_path, beam_chats_root)
    all_items = {item.identifier: item for item in live.load_manifest_items(base, longmemeval_path=longmemeval_path, beam_chats_root=beam_chats_root)}
    try:
        items = [all_items[item_id] for item_id in experiment["selected_item_ids"]]
    except KeyError as exc:
        raise live.LiveRunError("oracle-retrieval experiment item is not in the frozen base manifest") from exc
    runtime_root = runtime_root.resolve()
    live._secure_directory(runtime_root)
    live._secure_directory(runtime_root / "jobs")
    experiment_digest = controller._canonical_sha256(experiment)
    with concurrent.futures.ThreadPoolExecutor(max_workers=experiment["max_parallel_workers"]) as executor:
        rows = list(executor.map(lambda item: _run_item(item, base=base, experiment=experiment, experiment_digest=experiment_digest, source_python=source_python, scroll_source=scroll_source, runtime_root=runtime_root, credential_home=credential_home, resume=resume), items))
    rows.sort(key=lambda row: experiment["selected_item_ids"].index(row["task_id"]))
    model_calls = [row["model_scroll_repl_calls"] for row in rows]
    report = {"schema_version": 1, "experiment": experiment["experiment"], "experiment_manifest_sha256": experiment_digest, "base_memory_manifest_sha256": experiment["base_memory_manifest_sha256"], "base_memory_report_sha256": experiment["base_memory_report_sha256"], "policy_report_sha256": experiment["policy_report_sha256"], "controller_report_sha256": experiment["controller_report_sha256"], "implementation_commit": base["implementation_commit"], "controller_prompt_sha256": hashlib.sha256(controller.CONTROLLER_PROMPT.encode()).hexdigest(), "oracle_query_algorithm": experiment["oracle_query_algorithm"], "controller_retrieval_algorithm": experiment["controller_retrieval_algorithm"], "rows": rows, "oracle_retrieval": {"items": len(rows), "scroll_repl_calls": len(rows)}, "model_tool_adoption": {"items": len(rows), "items_with_scroll_repl": sum(call > 0 for call in model_calls), "scroll_repl_calls": sum(model_calls)}, "score_total": sum(row["score"] for row in rows)}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--experiment", type=Path)
    parser.add_argument("--base-manifest", type=Path)
    parser.add_argument("--base-report", type=Path)
    parser.add_argument("--policy-report", type=Path)
    parser.add_argument("--controller-report", type=Path)
    parser.add_argument("--longmemeval", type=Path)
    parser.add_argument("--beam-chats", type=Path)
    parser.add_argument("--scroll-source", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--credential-home", type=Path, default=Path.home() / ".hermes")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.worker:
        _worker(args.worker)
        return
    required = (args.experiment, args.base_manifest, args.base_report, args.policy_report, args.controller_report, args.longmemeval, args.beam_chats, args.scroll_source, args.runtime_root, args.output)
    if not all(required):
        parser.error("--experiment, --base-manifest, --base-report, --policy-report, --controller-report, --longmemeval, --beam-chats, --scroll-source, --runtime-root, and --output are required")
    report = run(args.experiment, args.base_manifest, args.base_report, args.policy_report, args.controller_report, longmemeval_path=args.longmemeval, beam_chats_root=args.beam_chats, scroll_source=args.scroll_source, runtime_root=args.runtime_root, output_path=args.output, credential_home=args.credential_home, resume=args.resume)
    print(json.dumps({"rows": len(report["rows"]), "score_total": report["score_total"], "oracle_retrieval": report["oracle_retrieval"], "model_tool_adoption": report["model_tool_adoption"]}, sort_keys=True))


if __name__ == "__main__":
    main()
