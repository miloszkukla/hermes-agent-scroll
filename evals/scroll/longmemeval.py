"""LongMemEval session ingestion through Hermes's immutable snapshot contract."""

from __future__ import annotations

import re
from typing import Any

from agent.context_engine import CanonicalHistoryRow, CanonicalHistorySnapshot


_DATE_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")


def to_iso_date(value: str | None) -> str | None:
    """Normalize a LongMemEval date to a sortable ISO day without guessing."""
    match = _DATE_RE.search(value or "")
    if not match:
        return None
    return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def _content(session_number: int, date: str | None, role: str, text: str) -> str:
    tag = f"[Session {session_number} | {date}]" if date else f"[Session {session_number}]"
    return f"{tag} {role}: {text.strip()}"


def snapshot_from_sessions(sessions: list[dict[str, Any]], task_id: str) -> CanonicalHistorySnapshot:
    """Materialize a deterministic, no-database LongMemEval seed projection.

    Gold answers and rubrics are intentionally not accepted by this adapter. A
    later reviewed driver may provide only the haystack sessions and question to
    the model under a frozen live manifest.
    """
    rows = []
    row_id = 1
    for session_number, session in enumerate(sessions, start=1):
        date = to_iso_date(session.get("date"))
        session_id = f"seed:{task_id}:s{session_number}"
        for turn in session.get("turns", []):
            role = str(turn.get("role") or "user")
            text = _content(session_number, date, role, str(turn.get("content") or ""))
            correlation = (("dataset", "longmemeval"), ("session", str(session_number)))
            if date:
                correlation += (("date", date),)
            rows.append(CanonicalHistoryRow(
                _row_id=row_id, generation=1, order_key=(1, row_id), session_id=session_id,
                role=role, text=text, content_reference=None, tool_name=None, tool_call_id=None,
                tool_calls=(), correlation=correlation, timestamp=None, sensitivity="normal",
                fidelity="text", is_compressed_summary=False,
            ))
            row_id += 1
    return CanonicalHistorySnapshot(f"longmemeval:{task_id}", 1, len(rows), tuple(rows))
