"""BEAM chat ingestion into a value-only Hermes history snapshot."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterator

from agent.context_engine import CanonicalHistoryRow, CanonicalHistorySnapshot


_MARKER = re.compile(r"\s*->->\s*[\d,]+")


def clean_content(value: str) -> str:
    return _MARKER.sub("", value or "").strip()


def to_iso_date(value: str | None) -> str | None:
    try:
        return datetime.strptime(value or "", "%B-%d-%Y").date().isoformat()
    except ValueError:
        return None


def _batch_date(batch: dict[str, Any]) -> str | None:
    if batch.get("time_anchor"):
        return str(batch["time_anchor"])
    for group in batch.get("turns", []):
        for message in group:
            if message.get("time_anchor"):
                return str(message["time_anchor"])
    return None


def iter_sessions(chat: list[dict[str, Any]]) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """Yield chronological BEAM sessions from the 100K and 10M source shapes."""
    for entry in chat:
        if not isinstance(entry, dict):
            raise ValueError("BEAM chat entry must be an object")
        if "batch_number" in entry:
            yield str(entry["batch_number"]), [entry]
            continue
        if len(entry) != 1:
            raise ValueError("BEAM 10M plan entry must have one session")
        session, batches = next(iter(entry.items()))
        if not isinstance(session, str) or not session.startswith("plan-") or not isinstance(batches, list):
            raise ValueError("BEAM 10M plan entry is malformed")
        if not all(isinstance(batch, dict) and "batch_number" in batch for batch in batches):
            raise ValueError("BEAM 10M plan batches are malformed")
        yield session, batches


def iter_turns(chat: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for session, batches in iter_sessions(chat):
        for batch in batches:
            batch_number = batch["batch_number"]
            anchor = _batch_date(batch)
            for group in batch.get("turns", []):
                for message in group:
                    yield {
                        "session": session,
                        "batch": batch_number,
                        "date": message.get("time_anchor") or anchor,
                        "id": message.get("id"),
                        "role": message.get("role") or "user",
                        "content": clean_content(str(message.get("content") or "")),
                    }


def snapshot_from_chat(chat: list[dict[str, Any]], task_id: str) -> CanonicalHistorySnapshot:
    rows = []
    for row_id, turn in enumerate(iter_turns(chat), start=1):
        date = to_iso_date(turn["date"])
        session = str(turn["session"])
        tag = f"[Session {session} | {date or turn['date']}]" if turn["date"] else f"[Session {session}]"
        correlation = (("dataset", "beam"), ("session", session), ("message_id", str(turn["id"])))
        if date:
            correlation += (("date", date),)
        rows.append(CanonicalHistoryRow(
            _row_id=row_id, generation=1, order_key=(1, row_id), session_id=f"seed:{task_id}:s{session}",
            role=turn["role"], text=f"{tag} {turn['role']}: {turn['content']}", content_reference=None,
            tool_name=None, tool_call_id=None, tool_calls=(), correlation=correlation, timestamp=None,
            sensitivity="normal", fidelity="text", is_compressed_summary=False,
        ))
    return CanonicalHistorySnapshot(f"beam:{task_id}", 1, len(rows), tuple(rows))
