"""Fail-closed Hermes executor for reviewed Scroll live evaluations.

Raw benchmark histories, gold answers, model responses, and provider traces stay
under the caller-provided ignored runtime directory. The durable report contains
only frozen identifiers, scores, response digests, and aggregate usage.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from agent.codex_headers import CODEX_AUX_BASE_URL
from .beam import iter_turns, to_iso_date as beam_date
from .live_manifest import validate_live_manifest
from .longmemeval import to_iso_date as longmemeval_date
from .paired_runner import PairedRunError, run_paired_evaluation


AGENT_SYSTEM_PROMPT = (
    "Answer the user's memory question only from the supplied conversation history. "
    "Do not invent facts. State concise, evidence-grounded answers, and explicitly "
    "say when the history does not contain the answer."
)
_REQUIRED_LONGMEMEVAL_TYPES = {"knowledge-update": 6, "multi-session": 6, "single-session-assistant": 5, "single-session-preference": 5, "single-session-user": 5, "temporal-reasoning": 5}
_REQUIRED_BEAM_TYPES = frozenset({"abstention", "contradiction_resolution", "event_ordering", "information_extraction", "instruction_following", "knowledge_update", "multi_session_reasoning", "preference_following", "summarization", "temporal_reasoning"})
CODING_SYSTEM_PROMPT = (
    "Work on the requested coding task in the current workspace. Use the terminal to inspect "
    "the files and tests, make the smallest correct fix, run the focused tests, and report the result."
)
_WORKER_ACCESS_TOKEN_MINIMUM_TTL_SECONDS = 1_260


class LiveRunError(RuntimeError):
    """The evaluated path could not uphold its frozen live-run contract."""


@dataclass(frozen=True)
class EvaluationItem:
    identifier: str
    benchmark: str
    question_type: str
    question: str
    history: tuple[dict[str, str], ...]
    gold: dict[str, Any]

    @property
    def public_probe(self) -> dict[str, str]:
        return {"id": self.identifier, "type": self.question_type, "question": self.question}


def agent_prompt_sha256() -> str:
    return hashlib.sha256(AGENT_SYSTEM_PROMPT.encode("utf-8")).hexdigest()


def coding_prompt_sha256() -> str:
    return hashlib.sha256(CODING_SYSTEM_PROMPT.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LiveRunError(f"could not read evaluation input {path}") from exc


def _resumable_worker_result(path: Path) -> dict[str, Any]:
    result = _read_json(path)
    usage = result.get("usage") if isinstance(result, dict) else None
    if not isinstance(result, dict) or not isinstance(result.get("answer"), str) or not result["answer"].strip() or not isinstance(usage, dict):
        raise LiveRunError("saved worker result is invalid")
    if any(not isinstance(usage.get(field), int) or isinstance(usage.get(field), bool) or usage[field] < 0 for field in ("input_tokens", "output_tokens", "cache_read_tokens")):
        raise LiveRunError("saved worker result has invalid usage")
    return result


def _secure_directory(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
        if not path.is_dir() or path.stat().st_mode & 0o077:
            raise OSError("directory permissions are not owner-only")
    except OSError as exc:
        raise LiveRunError(f"could not secure evaluation runtime directory {path}") from exc


def _write_private_json(path: Path, value: Mapping[str, Any]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(json.dumps(value))
    except OSError as exc:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise LiveRunError(f"could not write private evaluation input {path}") from exc


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise LiveRunError(f"could not hash required artifact {path}") from exc


def _command_output(args: list[str], failure: str, *, cwd: Path | None = None) -> str:
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True, timeout=30, cwd=cwd).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise LiveRunError(failure) from exc


def _git_output(args: list[str], failure: str) -> str:
    return _command_output(args, failure)


def _require_clean_git_checkout(path: Path, label: str, *, allow_untracked: bool = True) -> None:
    commands = (
        ["git", "-C", str(path), "diff", "--quiet"],
        ["git", "-C", str(path), "diff", "--cached", "--quiet"],
    )
    for command in commands:
        try:
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
        except subprocess.CalledProcessError as exc:
            raise LiveRunError(f"{label} checkout has tracked changes") from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise LiveRunError(f"could not verify {label} checkout cleanliness") from exc
    if not allow_untracked and _git_output(["git", "-C", str(path), "ls-files", "--others", "--exclude-standard"], f"could not verify {label} checkout cleanliness"):
        raise LiveRunError(f"{label} checkout has untracked files")


def verify_manifest_provenance(manifest: Mapping[str, Any], repository_root: Path) -> None:
    if _sha256(repository_root / "PLAN.md") != manifest["plan_sha256"]:
        raise LiveRunError("live manifest plan hash does not match this checkout")
    if _sha256(repository_root / "evals" / "scroll" / "manifest.json") != manifest["credential_free_manifest_sha256"]:
        raise LiveRunError("live manifest credential-free manifest hash does not match this checkout")
    implementation = manifest["implementation_commit"]
    _git_output(["git", "-C", str(repository_root), "cat-file", "-e", f"{implementation}^{{commit}}"], "live manifest implementation commit is unavailable")
    _git_output(["git", "-C", str(repository_root), "merge-base", "--is-ancestor", implementation, "HEAD"], "live manifest implementation commit is not an ancestor of HEAD")
    try:
        subprocess.run(
            ["git", "-C", str(repository_root), "diff", "--quiet", implementation, "HEAD", "--", ".", ":(exclude)plugins/context_engine/scroll/evidence/**"],
            check=True, capture_output=True, text=True, timeout=30,
        )
    except subprocess.CalledProcessError as exc:
        raise LiveRunError("checkout has implementation changes after the live manifest commit") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise LiveRunError("could not verify live manifest implementation provenance") from exc
    for command in (
        ["git", "-C", str(repository_root), "diff", "--quiet", "--", ".", ":(exclude)plugins/context_engine/scroll/evidence/**"],
        ["git", "-C", str(repository_root), "diff", "--cached", "--quiet", "--", ".", ":(exclude)plugins/context_engine/scroll/evidence/**"],
    ):
        try:
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
        except subprocess.CalledProcessError as exc:
            raise LiveRunError("checkout has uncommitted implementation changes") from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise LiveRunError("could not verify live manifest implementation provenance") from exc
    untracked = _git_output(
        ["git", "-C", str(repository_root), "ls-files", "--others", "--exclude-standard", "--", ".", ":(exclude)plugins/context_engine/scroll/evidence/**"],
        "could not verify live manifest implementation provenance",
    )
    if untracked:
        raise LiveRunError("checkout has uncommitted implementation changes")


def _history_row(session: int, date: str | None, role: str, content: str) -> dict[str, str]:
    tag = f"[Session {session} | {date}]" if date else f"[Session {session}]"
    return {"role": role, "content": f"{tag} {role}: {content.strip()}"}


def _auxiliary_usage(db: Any, session_id: str, expected_model: str) -> tuple[int, int, int]:
    try:
        with db._read_ctx() as conn:
            rows = conn.execute(
                "SELECT COALESCE(input_tokens, 0), COALESCE(output_tokens, 0), COALESCE(cache_read_tokens, 0), model, billing_provider "
                "FROM session_model_usage WHERE session_id = ? AND task <> ''", (session_id,),
            ).fetchall()
        if any(row[3] != expected_model or row[4] not in {"", "openai-codex"} for row in rows):
            raise LiveRunError("auxiliary evaluation left the ChatGPT Codex OAuth route")
        return tuple(sum(int(row[index] or 0) for row in rows) for index in range(3))
    except Exception as exc:
        if isinstance(exc, LiveRunError):
            raise
        raise LiveRunError("could not account for auxiliary evaluation usage") from exc


def _prepare_coding_scenario(agent: Any, history: list[dict[str, Any]], system_message: str, scenario: str, runtime_home: Path, rebuild: Any) -> tuple[Any, list[dict[str, Any]]]:
    if scenario == "automatic-compaction":
        return agent, history
    if scenario == "manual-compaction":
        compress = getattr(agent, "_compress_context", None)
        if not callable(compress):
            raise LiveRunError("coding manual-compaction arm has no host compression lifecycle")
        compressed, _ = compress(history, system_message, force=True)
        return agent, compressed
    if scenario == "cache-loss-resume":
        agent.close()
        shutil.rmtree(runtime_home / "cache" / "scroll", ignore_errors=True)
        return rebuild(), history
    raise LiveRunError(f"unknown coding scenario: {scenario}")


def _enabled_toolsets(arm: str, coding: bool) -> list[str]:
    if arm not in {"stock", "scroll"}:
        raise LiveRunError(f"unknown evaluation arm: {arm}")
    if coding:
        return ["terminal", "file", "context_engine"] if arm == "scroll" else ["terminal", "file"]
    return ["context_engine"] if arm == "scroll" else []


def load_longmemeval_items(dataset_path: Path, identifiers: Sequence[str]) -> list[EvaluationItem]:
    records = _read_json(dataset_path)
    if not isinstance(records, list):
        raise LiveRunError("LongMemEval source must be a JSON list")
    by_id = {f"longmemeval/{row.get('question_id')}": row for row in records if isinstance(row, dict)}
    result = []
    for identifier in identifiers:
        row = by_id.get(identifier)
        if row is None:
            raise LiveRunError(f"manifest LongMemEval item is absent: {identifier}")
        history = []
        sessions = row.get("haystack_sessions") or []
        dates = row.get("haystack_dates") or []
        for number, turns in enumerate(sessions, start=1):
            date = longmemeval_date(str(dates[number - 1])) if number <= len(dates) else None
            if not isinstance(turns, list):
                raise LiveRunError(f"LongMemEval item has malformed sessions: {identifier}")
            for turn in turns:
                if not isinstance(turn, dict):
                    raise LiveRunError(f"LongMemEval item has malformed turn: {identifier}")
                history.append(_history_row(number, date, str(turn.get("role") or "user"), str(turn.get("content") or "")))
        question = row.get("question")
        question_type = row.get("question_type")
        answer = row.get("answer")
        if not all(isinstance(value, str) and value for value in (question, question_type)) or answer is None or not history:
            raise LiveRunError(f"LongMemEval item is incomplete: {identifier}")
        result.append(EvaluationItem(
            identifier, "longmemeval", question_type, question, tuple(history),
            {"question": question, "answer": answer, "question_type": question_type, "is_abstention": "_abs" in identifier},
        ))
    return result


def _beam_identifier_parts(identifier: str) -> tuple[str, str, str, int]:
    parts = identifier.split("/")
    if len(parts) != 4 or parts[0] != "beam" or not parts[1] or not parts[2] or "-" not in parts[3]:
        raise LiveRunError(f"invalid BEAM item id: {identifier}")
    question_type, index = parts[3].rsplit("-", 1)
    try:
        return parts[1], parts[2], question_type, int(index)
    except ValueError as exc:
        raise LiveRunError(f"invalid BEAM question index: {identifier}") from exc


def load_beam_items(chats_root: Path, identifiers: Sequence[str]) -> list[EvaluationItem]:
    cache: dict[tuple[str, str], tuple[list[dict[str, str]], dict[str, list[dict[str, Any]]]]] = {}
    result = []
    for identifier in identifiers:
        scale, conversation, question_type, question_index = _beam_identifier_parts(identifier)
        key = (scale, conversation)
        if key not in cache:
            root = chats_root / scale / conversation
            chat = _read_json(root / "chat.json")
            questions = _read_json(root / "probing_questions" / "probing_questions.json")
            if not isinstance(chat, list) or not isinstance(questions, dict):
                raise LiveRunError(f"BEAM conversation is malformed: {scale}/{conversation}")
            history = []
            for turn in iter_turns(chat):
                date = beam_date(turn["date"])
                history.append(_history_row(int(turn["batch"]), date, turn["role"], turn["content"]))
            cache[key] = history, questions
        history, grouped_questions = cache[key]
        questions = grouped_questions.get(question_type)
        if not isinstance(questions, list) or question_index < 0 or question_index >= len(questions):
            raise LiveRunError(f"BEAM question is absent: {identifier}")
        gold = questions[question_index]
        question = gold.get("question") if isinstance(gold, dict) else None
        if not isinstance(question, str) or not question or not history:
            raise LiveRunError(f"BEAM question is incomplete: {identifier}")
        result.append(EvaluationItem(identifier, "beam", question_type, question, tuple(history), dict(gold)))
    return result


def load_manifest_items(manifest: Mapping[str, Any], *, longmemeval_path: Path, beam_chats_root: Path) -> list[EvaluationItem]:
    datasets = {dataset["name"]: dataset["item_ids"] for dataset in manifest["datasets"]}
    expected = {"longmemeval", "beam"}
    if set(datasets) != expected:
        raise LiveRunError("live manifest must freeze exactly longmemeval and beam")
    longmemeval = load_longmemeval_items(longmemeval_path, datasets["longmemeval"])
    beam = load_beam_items(beam_chats_root, datasets["beam"])
    if len(longmemeval) != 32 or len(beam) != 16:
        raise LiveRunError("memory manifest must retain exactly 32 LongMemEval and 16 BEAM items")
    if Counter(item.question_type for item in longmemeval) != _REQUIRED_LONGMEMEVAL_TYPES:
        raise LiveRunError("memory manifest LongMemEval selection is not the frozen stratified set")
    if {item.question_type for item in beam} != _REQUIRED_BEAM_TYPES:
        raise LiveRunError("memory manifest BEAM selection is not the frozen type coverage")
    return [*longmemeval, *beam]


def verify_memory_inputs(manifest: Mapping[str, Any], longmemeval_path: Path, beam_chats_root: Path) -> None:
    revisions = manifest["source_revisions"]
    longmemeval_root = longmemeval_path.parents[1]
    beam_root = beam_chats_root.parent
    _require_clean_git_checkout(longmemeval_root, "LongMemEval source")
    _require_clean_git_checkout(beam_root, "BEAM source")
    if _git_output(["git", "-C", str(longmemeval_root), "rev-parse", "HEAD"], "could not verify LongMemEval source revision") != revisions.get("longmemeval"):
        raise LiveRunError("LongMemEval source revision does not match the live manifest")
    if _git_output(["git", "-C", str(beam_root), "rev-parse", "HEAD"], "could not verify BEAM source revision") != revisions.get("beam"):
        raise LiveRunError("BEAM source revision does not match the live manifest")
    expected_hash = ""
    for part in str(next(dataset["revision"] for dataset in manifest["datasets"] if dataset["name"] == "longmemeval")).split(";"):
        part = part.strip()
        if part.startswith("sha256:"):
            expected_hash = part.removeprefix("sha256:")
    if len(expected_hash) != 64 or _sha256(longmemeval_path) != expected_hash:
        raise LiveRunError("LongMemEval corpus hash does not match the live manifest")


def _build_live_agent(factory: Any, job: Mapping[str, Any], session_id: str, db: Any, toolsets: list[str]) -> Any:
    return factory(
        provider="openai-codex", api_key=job["api_key"], base_url=CODEX_AUX_BASE_URL, api_mode="codex_responses", model=job["model"], session_id=session_id, session_db=db,
        enabled_toolsets=toolsets, quiet_mode=True, skip_context_files=True, skip_memory=True,
        skip_background_review=True, platform="cli", max_iterations=int(job["max_iterations"]),
        max_tokens=int(job["max_output_tokens"]), reasoning_config={"enabled": False}, fallback_model=[],
    )


def _require_chatgpt_codex_oauth(hermes_home: Path) -> None:
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from hermes_cli.auth import get_codex_auth_status

    token = set_hermes_home_override(hermes_home)
    try:
        logged_in = get_codex_auth_status().get("logged_in")
    finally:
        reset_hermes_home_override(token)
    if not logged_in:
        raise LiveRunError("ChatGPT Codex OAuth credential is unavailable")


def _lease_chatgpt_codex_access_token(hermes_home: Path, resolver: Any = None) -> str:
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from hermes_cli.auth import _decode_jwt_claims, resolve_codex_runtime_credentials

    token = set_hermes_home_override(hermes_home)
    try:
        credentials = (resolver or resolve_codex_runtime_credentials)(refresh_if_expiring=True, refresh_skew_seconds=_WORKER_ACCESS_TOKEN_MINIMUM_TTL_SECONDS)
    finally:
        reset_hermes_home_override(token)
    api_key = credentials.get("api_key")
    if not isinstance(api_key, str) or not api_key.strip():
        raise LiveRunError("parent-managed ChatGPT Codex OAuth lease is unavailable")
    api_key = api_key.strip()
    source = credentials.get("source")
    if source == "credential_pool":
        exp = _decode_jwt_claims(api_key).get("exp")
        if not isinstance(exp, (int, float)) or not math.isfinite(float(exp)) or float(exp) <= time.time() + _WORKER_ACCESS_TOKEN_MINIMUM_TTL_SECONDS:
            raise LiveRunError("parent-managed ChatGPT Codex credential-pool lease needs a verifiable 21-minute lifetime")
    elif source != "hermes-auth-store":
        raise LiveRunError("evaluation requires a parent-managed ChatGPT Codex OAuth store or credential pool")
    return api_key


def _isolated_subprocess_environment() -> dict[str, str]:
    repository_root = Path(__file__).resolve().parents[2]
    return {"HOME": "/tmp", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PATH": os.pathsep.join((str(Path(sys.executable).parent), os.defpath)), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PYTHONPATH": str(repository_root)}


def _configure_coding_workspace(workspace: Path, session_id: str, register: Any) -> None:
    if not workspace.is_dir():
        raise LiveRunError("coding workspace is unavailable")
    os.environ["TERMINAL_CWD"] = str(workspace)
    register(session_id, {"cwd": str(workspace)})


def _worker_config(job: Mapping[str, Any]) -> str:
    return (
        "model:\n"
        f"  context_length: {job['context_window']}\n"
        "context:\n"
        f"  engine: {'scroll' if job['arm'] == 'scroll' else 'compressor'}\n"
        "compression:\n"
        "  enabled: true\n"
        "  threshold: 0.75\n"
        "approvals:\n"
        "  mode: \"off\"\n"
        "auxiliary:\n"
        "  compression:\n"
        "    provider: openai-codex\n"
        f"    model: {job['model']}\n"
        "    api_mode: codex_responses\n"
        "    reasoning_effort: none\n"
        f"    max_output_tokens: {job['max_output_tokens']}\n"
    )


def _worker_result(job_path: Path) -> None:
    job = _read_json(job_path)
    api_key = job.get("api_key")
    if not isinstance(api_key, str) or not api_key.strip():
        raise LiveRunError("worker access-token lease is unavailable")
    try:
        job_path.unlink()
    except OSError as exc:
        raise LiveRunError("worker access-token lease could not be removed") from exc
    runtime_home = Path(job["runtime_home"])
    runtime_home.mkdir(parents=True, exist_ok=True)
    (runtime_home / "config.yaml").write_text(_worker_config(job), encoding="utf-8")
    os.environ["HERMES_HOME"] = str(runtime_home)
    coding = job.get("lane") == "coding"
    workspace = None
    if coding:
        workspace = Path(str(job.get("workspace") or ""))
    from hermes_state import SessionDB
    from run_agent import AIAgent

    db = SessionDB(runtime_home / "state.db")
    session_id = f"scroll-eval-{uuid.uuid4().hex}"
    db.create_session(session_id, source="eval", model=job["model"])
    db.append_messages_batch(session_id, job["history"], chunk_rows=256)
    history = db.get_messages_as_conversation(session_id, repair_alternation=True, include_row_ids=True)
    toolsets = _enabled_toolsets(job["arm"], coding)
    clear_workspace = None
    if coding:
        from tools.terminal_tool import clear_task_env_overrides, register_task_env_overrides

        _configure_coding_workspace(workspace, session_id, register_task_env_overrides)
        clear_workspace = clear_task_env_overrides
    from agent.aux_accounting import reset_accounting_context, set_accounting_context

    accounting_failures = []
    accounting_token = set_accounting_context(db, session_id, failure_sink=accounting_failures)
    agent = None
    try:
        def build_agent():
            return _build_live_agent(AIAgent, job, session_id, db, toolsets)

        agent = build_agent()
        if getattr(agent, "provider", None) != "openai-codex" or getattr(agent, "api_mode", None) != "codex_responses" or getattr(agent, "model", None) != job["model"]:
            raise LiveRunError("evaluation agent left the ChatGPT Codex OAuth route")
        scenario_latency_seconds = 0.0
        if coding:
            scenario_started = time.monotonic()
            agent, history = _prepare_coding_scenario(agent, history, CODING_SYSTEM_PROMPT, str(job.get("scenario") or ""), runtime_home, build_agent)
            scenario_latency_seconds = time.monotonic() - scenario_started
        response = agent.run_conversation(
            job["probe"]["question"], system_message=CODING_SYSTEM_PROMPT if coding else AGENT_SYSTEM_PROMPT,
            conversation_history=history, task_id=session_id if coding else None,
        )
        answer = response.get("final_response") if isinstance(response, dict) else None
        if not isinstance(answer, str) or not answer.strip() or (isinstance(response, dict) and response.get("failed")):
            raise LiveRunError("Hermes evaluation arm failed before a final answer")
        if int(getattr(agent, "session_api_calls", 0) or 0) <= 0 or int(getattr(agent, "session_output_tokens", 0) or 0) <= 0:
            raise LiveRunError("Hermes evaluation arm omitted main-model usage")
        if accounting_failures:
            raise LiveRunError("auxiliary evaluation accounting failed")
        input_tokens = int(getattr(agent, "session_input_tokens", 0) or 0)
        output_tokens = int(getattr(agent, "session_output_tokens", 0) or 0)
        cache_read_tokens = int(getattr(agent, "session_cache_read_tokens", 0) or 0)
        auxiliary_input, auxiliary_output, auxiliary_cache_read = _auxiliary_usage(db, session_id, job["model"])
        input_tokens += auxiliary_input
        output_tokens += auxiliary_output
        cache_read_tokens += auxiliary_cache_read
        Path(job["result_path"]).write_text(json.dumps({
            "answer": answer, "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "cache_read_tokens": cache_read_tokens},
            "scenario_latency_seconds": scenario_latency_seconds,
        }), encoding="utf-8")
    finally:
        reset_accounting_context(accounting_token)
        if agent is not None:
            agent.close()
        if clear_workspace is not None:
            clear_workspace(session_id)
        db.close()


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
        reply = self.client.chat.completions.create(model=self.model, messages=messages, max_tokens=payload["max_output_tokens"])
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
if payload["benchmark"] == "longmemeval":
    from scroll_eval.evals.longmemeval.judge.metrics import score_one
    score = score_one(judge, payload["gold"], payload["answer"])
elif payload["benchmark"] == "beam":
    from scroll_eval.evals.beam.judge.metrics import evaluate, primary_score
    outcome = evaluate(payload["question_type"], payload["gold"].get("rubric", []), payload["answer"], judge, question=payload["gold"].get("question", ""), max_workers=1)
    score = primary_score(payload["question_type"], outcome)
else:
    raise RuntimeError("unknown benchmark")
print(json.dumps({"score": score, "usage": usage}))
'''


def _judge_item(item: EvaluationItem, answer: str, manifest: Mapping[str, Any], source_python: Path, scroll_source: Path, api_key: str) -> dict[str, Any]:
    payload = {
        "benchmark": item.benchmark, "question_type": item.question_type, "gold": item.gold, "answer": answer,
        "model": manifest["judge_model"], "max_output_tokens": manifest["max_output_tokens"], "api_key": api_key,
    }
    with tempfile.TemporaryDirectory(prefix="scroll-eval-judge-") as judge_home:
        judge_env = _isolated_subprocess_environment()
        judge_env["HERMES_HOME"] = judge_home
        try:
            process = subprocess.run(
                [str(source_python), "-c", _JUDGE_PROGRAM], input=json.dumps(payload), text=True,
                cwd=scroll_source, env=judge_env, capture_output=True, check=True, timeout=600,
            )
            result = json.loads(process.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            raise LiveRunError(f"pinned {item.benchmark} judge failed") from exc
    usage = result.get("usage") if isinstance(result, dict) else None
    if not isinstance(result, dict) or not isinstance(result.get("score"), (int, float)) or isinstance(result["score"], bool) or not isinstance(usage, dict):
        raise LiveRunError(f"pinned {item.benchmark} judge returned an invalid result")
    usage_fields = ("input_tokens", "output_tokens", "cache_read_tokens")
    if any(not isinstance(usage.get(field), int) or isinstance(usage.get(field), bool) for field in usage_fields):
        raise LiveRunError(f"pinned {item.benchmark} judge returned incomplete usage")
    input_tokens = usage["input_tokens"]
    output_tokens = usage["output_tokens"]
    cache_read_tokens = usage["cache_read_tokens"]
    if input_tokens < 0 or output_tokens <= 0 or cache_read_tokens < 0 or input_tokens + cache_read_tokens <= 0:
        raise LiveRunError(f"pinned {item.benchmark} judge returned invalid usage")
    return {"score": float(result["score"]), "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "cache_read_tokens": cache_read_tokens}}


def run_live_evaluation(
    manifest_path: Path, *, longmemeval_path: Path, beam_chats_root: Path, scroll_source: Path,
    runtime_root: Path, output_path: Path, credential_home: Path = Path.home() / ".hermes", resume: bool = False,
) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise LiveRunError("live manifest must be a JSON object")
    validate_live_manifest(manifest)
    repository_root = Path(__file__).resolve().parents[2]
    verify_manifest_provenance(manifest, repository_root)
    if manifest["agent_prompt_sha256"] != agent_prompt_sha256():
        raise LiveRunError("live manifest does not freeze this executor's agent prompt")
    source_commit = _git_output(["git", "-C", str(scroll_source), "rev-parse", "HEAD"], "could not verify pinned Scroll source revision")
    if source_commit != manifest["source_revisions"].get("scroll"):
        raise LiveRunError("pinned Scroll source revision does not match the live manifest")
    _require_clean_git_checkout(scroll_source, "pinned Scroll source", allow_untracked=False)
    source_python = scroll_source / ".venv" / "bin" / "python"
    if not source_python.is_file():
        raise LiveRunError("pinned Scroll evaluation environment is unavailable")
    source_module = _command_output(
        [str(source_python), "-c", "import scroll_eval; from pathlib import Path; print(Path(scroll_eval.__file__).resolve())"],
        "pinned Scroll evaluation environment cannot import scroll_eval",
        cwd=scroll_source,
    )
    try:
        Path(source_module).resolve().relative_to((scroll_source / "evaluation" / "scroll_eval").resolve())
    except ValueError as exc:
        raise LiveRunError("pinned Scroll evaluation environment imports an unexpected scroll_eval") from exc
    if not credential_home.is_dir():
        raise LiveRunError("credential home is unavailable")
    _require_chatgpt_codex_oauth(credential_home)
    verify_memory_inputs(manifest, longmemeval_path, beam_chats_root)
    items = load_manifest_items(manifest, longmemeval_path=longmemeval_path, beam_chats_root=beam_chats_root)
    by_id = {item.identifier: item for item in items}
    if len(by_id) != len(items):
        raise LiveRunError("live manifest item ids are not globally unique")
    runtime_root = runtime_root.resolve()
    _secure_directory(runtime_root)
    _secure_directory(runtime_root / "jobs")

    def execute(arm: str, probe: Mapping[str, str]) -> Mapping[str, Any]:
        item = by_id.get(probe["id"])
        if item is None or item.public_probe != dict(probe):
            raise LiveRunError("executor received an unfrozen model probe")
        job_root = runtime_root / "jobs" / hashlib.sha256(f"{arm}:{item.identifier}".encode()).hexdigest()
        _secure_directory(job_root)
        result_path = job_root / "result.json"
        if resume and result_path.is_file():
            return _resumable_worker_result(result_path)
        job_path = job_root / "job.json"
        _write_private_json(job_path, {
            "arm": arm, "model": manifest["agent_model"], "context_window": manifest["context_window_tokens"],
            "max_iterations": manifest["max_iterations"], "temperature": manifest["temperature"], "seed": manifest["seed"], "max_output_tokens": manifest["max_output_tokens"], "output_token_budget": manifest["output_token_budget"], "cache_read_token_budget": manifest["cache_read_token_budget"],
            "history": item.history, "probe": item.public_probe, "runtime_home": str(job_root / "home"),
            "api_key": _lease_chatgpt_codex_access_token(credential_home), "result_path": str(result_path),
        })
        try:
            subprocess.run([sys.executable, "-m", "evals.scroll.hermes_live", "--worker", str(job_path)], cwd=Path(__file__).resolve().parents[2], env=_isolated_subprocess_environment(), check=True, capture_output=True, text=True, timeout=900)
            result = _read_json(result_path)
        except (OSError, subprocess.SubprocessError, LiveRunError) as exc:
            raise LiveRunError(f"Hermes {arm} arm failed for {item.identifier}") from exc
        finally:
            job_path.unlink(missing_ok=True)
        if not isinstance(result, dict) or not isinstance(result.get("answer"), str) or not isinstance(result.get("usage"), dict):
            raise LiveRunError(f"Hermes {arm} arm produced an invalid result")
        return result

    def judge(probe: Mapping[str, Any], answer: str) -> Mapping[str, Any]:
        item = by_id.get(str(probe.get("id")))
        if item is None:
            raise LiveRunError("judge received an unfrozen probe")
        return _judge_item(item, answer, manifest, source_python, scroll_source, _lease_chatgpt_codex_access_token(credential_home))

    try:
        report = run_paired_evaluation(manifest, [item.public_probe for item in items], execute, judge)
    except PairedRunError as exc:
        raise LiveRunError(str(exc)) from exc
    report.update({
        "schema_version": 1, "implementation_commit": manifest["implementation_commit"],
        "source_revisions": manifest["source_revisions"], "licenses": manifest["licenses"],
        "agent_prompt_sha256": manifest["agent_prompt_sha256"],
    })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--longmemeval", type=Path)
    parser.add_argument("--beam-chats", type=Path)
    parser.add_argument("--scroll-source", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.worker:
        _worker_result(args.worker)
        return
    required = (args.manifest, args.longmemeval, args.beam_chats, args.scroll_source, args.runtime_root, args.output)
    if not all(required):
        parser.error("--manifest, --longmemeval, --beam-chats, --scroll-source, --runtime-root, and --output are required")
    report = run_live_evaluation(
        args.manifest, longmemeval_path=args.longmemeval, beam_chats_root=args.beam_chats,
        scroll_source=args.scroll_source, runtime_root=args.runtime_root, output_path=args.output,
        resume=args.resume,
    )
    print(json.dumps({"manifest_sha256": report["manifest_sha256"], "billing_mode": report["billing_mode"], "rows": len(report["rows"])}, sort_keys=True))


if __name__ == "__main__":
    main()
