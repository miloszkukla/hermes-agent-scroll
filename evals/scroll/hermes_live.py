"""Fail-closed Hermes executor for reviewed Scroll live evaluations.

Raw benchmark histories, gold answers, model responses, and provider traces stay
under the caller-provided ignored runtime directory. The durable report contains
only frozen identifiers, scores, response digests, and aggregate usage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .beam import iter_turns, to_iso_date as beam_date
from .live_manifest import validate_live_manifest
from .longmemeval import to_iso_date as longmemeval_date
from .paired_runner import PairedRunError, run_paired_evaluation


AGENT_SYSTEM_PROMPT = (
    "Answer the user's memory question only from the supplied conversation history. "
    "Do not invent facts. State concise, evidence-grounded answers, and explicitly "
    "say when the history does not contain the answer."
)
CODING_SYSTEM_PROMPT = (
    "Work on the requested coding task in the current workspace. Use the terminal to inspect "
    "the files and tests, make the smallest correct fix, run the focused tests, and report the result."
)


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


def _history_row(session: int, date: str | None, role: str, content: str) -> dict[str, str]:
    tag = f"[Session {session} | {date}]" if date else f"[Session {session}]"
    return {"role": role, "content": f"{tag} {role}: {content.strip()}"}


def _auxiliary_usage(db: Any, session_id: str) -> tuple[int, int]:
    try:
        with db._read_ctx() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0) "
                "FROM session_model_usage WHERE session_id = ? AND task <> ''", (session_id,),
            ).fetchone()
        return int(row[0] or 0), int(row[1] or 0)
    except Exception as exc:
        raise LiveRunError("could not account for auxiliary evaluation usage") from exc


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
        if not all(isinstance(value, str) and value for value in (question, question_type, answer)) or not history:
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
    return [
        *load_longmemeval_items(longmemeval_path, datasets["longmemeval"]),
        *load_beam_items(beam_chats_root, datasets["beam"]),
    ]


def _worker_result(job_path: Path) -> None:
    job = _read_json(job_path)
    runtime_home = Path(job["runtime_home"])
    runtime_home.mkdir(parents=True, exist_ok=True)
    (runtime_home / "config.yaml").write_text(
        "model:\n"
        f"  context_length: {job['context_window']}\n"
        "context:\n"
        f"  engine: {'scroll' if job['arm'] == 'scroll' else 'compressor'}\n"
        "compression:\n"
        "  enabled: true\n"
        "  threshold: 0.75\n"
        "auxiliary:\n"
        "  compression:\n"
        "    provider: openrouter\n"
        f"    model: {job['model']}\n"
        "    reasoning_effort: none\n"
        f"    max_output_tokens: {job['output_token_budget']}\n",
        encoding="utf-8",
    )
    os.environ["HERMES_HOME"] = str(runtime_home)
    coding = job.get("lane") == "coding"
    if coding:
        workspace = Path(str(job.get("workspace") or ""))
        if not workspace.is_dir():
            raise LiveRunError("coding workspace is unavailable")
        os.environ["TERMINAL_CWD"] = str(workspace)
    from hermes_cli.env_loader import load_hermes_dotenv

    load_hermes_dotenv(hermes_home=job["credential_home"], load_external_secrets=False)
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise LiveRunError("OpenRouter credential was not loaded")
    from hermes_state import SessionDB
    from run_agent import AIAgent

    db = SessionDB(runtime_home / "state.db")
    session_id = f"scroll-eval-{uuid.uuid4().hex}"
    db.create_session(session_id, source="eval", model=job["model"])
    db.append_messages_batch(session_id, job["history"], chunk_rows=256)
    history = db.get_messages_as_conversation(session_id, repair_alternation=True, include_row_ids=True)
    toolsets = ["context_engine"] if job["arm"] == "scroll" else []
    agent = None
    try:
        agent = AIAgent(
            provider="openrouter", model=job["model"], session_id=session_id, session_db=db,
            enabled_toolsets=toolsets, quiet_mode=True, skip_context_files=True, skip_memory=True,
            skip_background_review=True, platform="cli", max_iterations=int(job["max_iterations"]),
            max_tokens=int(job["max_output_tokens"]), reasoning_config={"enabled": False},
            request_overrides={"seed": job["seed"]},
        )
        response = agent.run_conversation(
            job["probe"]["question"], system_message=CODING_SYSTEM_PROMPT if coding else AGENT_SYSTEM_PROMPT,
            conversation_history=history,
        )
        answer = response.get("final_response") if isinstance(response, dict) else None
        if not isinstance(answer, str) or not answer.strip() or (isinstance(response, dict) and response.get("failed")):
            raise LiveRunError("Hermes evaluation arm failed before a final answer")
        input_tokens = int(getattr(agent, "session_input_tokens", 0) or 0)
        output_tokens = int(getattr(agent, "session_output_tokens", 0) or 0)
        auxiliary_input, auxiliary_output = _auxiliary_usage(db, session_id)
        input_tokens += auxiliary_input
        output_tokens += auxiliary_output
        cost = input_tokens * float(job["input_price_per_token"]) + output_tokens * float(job["output_price_per_token"])
        Path(job["result_path"]).write_text(json.dumps({
            "answer": answer, "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": cost},
        }), encoding="utf-8")
    finally:
        if agent is not None:
            agent.close()
        db.close()


_JUDGE_PROGRAM = r'''
import json, os, sys, threading
from types import SimpleNamespace
from openai import OpenAI

payload = json.load(sys.stdin)
usage = {"input_tokens": 0, "output_tokens": 0}
lock = threading.Lock()

class Judge:
    def __init__(self):
        self.client = OpenAI(api_key=os.environ["OPENROUTER_API_KEY"], base_url="https://openrouter.ai/api/v1", max_retries=2, timeout=120)
    def invoke(self, prompt):
        messages = [{"role": "user", "content": prompt}] if isinstance(prompt, str) else list(prompt)
        reply = self.client.chat.completions.create(model=payload["model"], messages=messages, seed=payload["seed"], max_tokens=payload["max_output_tokens"])
        with lock:
            usage["input_tokens"] += int(getattr(reply.usage, "prompt_tokens", 0) or 0)
            usage["output_tokens"] += int(getattr(reply.usage, "completion_tokens", 0) or 0)
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


def _judge_item(item: EvaluationItem, answer: str, manifest: Mapping[str, Any], source_python: Path) -> dict[str, Any]:
    payload = {
        "benchmark": item.benchmark, "question_type": item.question_type, "gold": item.gold, "answer": answer,
        "model": manifest["judge_model"], "seed": manifest["seed"], "max_output_tokens": manifest["max_output_tokens"],
    }
    try:
        process = subprocess.run(
            [str(source_python), "-c", _JUDGE_PROGRAM], input=json.dumps(payload), text=True,
            capture_output=True, check=True, timeout=600,
        )
        result = json.loads(process.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise LiveRunError(f"pinned {item.benchmark} judge failed") from exc
    usage = result.get("usage") if isinstance(result, dict) else None
    if not isinstance(result, dict) or not isinstance(result.get("score"), (int, float)) or isinstance(result["score"], bool) or not isinstance(usage, dict):
        raise LiveRunError(f"pinned {item.benchmark} judge returned an invalid result")
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    if input_tokens < 0 or output_tokens < 0:
        raise LiveRunError(f"pinned {item.benchmark} judge returned invalid usage")
    cost = input_tokens * float(manifest["input_price_per_token"]) + output_tokens * float(manifest["output_price_per_token"])
    return {"score": float(result["score"]), "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": cost}}


def run_live_evaluation(
    manifest_path: Path, *, longmemeval_path: Path, beam_chats_root: Path, scroll_source: Path,
    runtime_root: Path, output_path: Path, credential_home: Path = Path.home() / ".hermes",
) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise LiveRunError("live manifest must be a JSON object")
    validate_live_manifest(manifest)
    if manifest["agent_prompt_sha256"] != agent_prompt_sha256():
        raise LiveRunError("live manifest does not freeze this executor's agent prompt")
    try:
        source_commit = subprocess.run(
            ["git", "-C", str(scroll_source), "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise LiveRunError("could not verify pinned Scroll source revision") from exc
    if source_commit != manifest["source_revisions"].get("scroll"):
        raise LiveRunError("pinned Scroll source revision does not match the live manifest")
    source_python = scroll_source / ".venv" / "bin" / "python"
    if not source_python.is_file():
        raise LiveRunError("pinned Scroll evaluation environment is unavailable")
    if not credential_home.is_dir():
        raise LiveRunError("credential home is unavailable")
    from hermes_cli.env_loader import load_hermes_dotenv

    load_hermes_dotenv(hermes_home=credential_home, load_external_secrets=False)
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise LiveRunError("OpenRouter credential was not loaded")
    items = load_manifest_items(manifest, longmemeval_path=longmemeval_path, beam_chats_root=beam_chats_root)
    by_id = {item.identifier: item for item in items}
    if len(by_id) != len(items):
        raise LiveRunError("live manifest item ids are not globally unique")
    runtime_root.mkdir(parents=True, exist_ok=True)

    def execute(arm: str, probe: Mapping[str, str]) -> Mapping[str, Any]:
        item = by_id.get(probe["id"])
        if item is None or item.public_probe != dict(probe):
            raise LiveRunError("executor received an unfrozen model probe")
        job_root = runtime_root / "jobs" / hashlib.sha256(f"{arm}:{item.identifier}".encode()).hexdigest()
        job_root.mkdir(parents=True, exist_ok=True)
        result_path = job_root / "result.json"
        job_path = job_root / "job.json"
        job_path.write_text(json.dumps({
            "arm": arm, "model": manifest["agent_model"], "context_window": manifest["context_window_tokens"],
            "max_iterations": manifest["max_iterations"], "temperature": manifest["temperature"], "seed": manifest["seed"], "max_output_tokens": manifest["max_output_tokens"], "output_token_budget": manifest["output_token_budget"],
            "input_price_per_token": manifest["input_price_per_token"], "output_price_per_token": manifest["output_price_per_token"],
            "history": item.history, "probe": item.public_probe, "runtime_home": str(job_root / "home"),
            "credential_home": str(credential_home), "result_path": str(result_path),
        }), encoding="utf-8")
        try:
            subprocess.run([sys.executable, "-m", "evals.scroll.hermes_live", "--worker", str(job_path)], cwd=Path(__file__).resolve().parents[2], check=True, capture_output=True, text=True, timeout=900)
            result = _read_json(result_path)
        except (OSError, subprocess.SubprocessError, LiveRunError) as exc:
            raise LiveRunError(f"Hermes {arm} arm failed for {item.identifier}") from exc
        if not isinstance(result, dict) or not isinstance(result.get("answer"), str) or not isinstance(result.get("usage"), dict):
            raise LiveRunError(f"Hermes {arm} arm produced an invalid result")
        return result

    def judge(probe: Mapping[str, Any], answer: str) -> Mapping[str, Any]:
        item = by_id.get(str(probe.get("id")))
        if item is None:
            raise LiveRunError("judge received an unfrozen probe")
        return _judge_item(item, answer, manifest, source_python)

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
    )
    print(json.dumps({"manifest_sha256": report["manifest_sha256"], "total_cost_usd": report["total_cost_usd"], "rows": len(report["rows"])}, sort_keys=True))


if __name__ == "__main__":
    main()
