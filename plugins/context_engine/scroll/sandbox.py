"""Monty-only persistent REPL and value-only Scroll recall callbacks."""

from __future__ import annotations

import ast
import base64
import csv
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import signal
import sqlite3
import sys
import sysconfig
import threading
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

from agent.context_engine import CanonicalHistorySnapshot


MAX_SOURCE_CHARS = 4_096
MAX_OUTPUT_BYTES = 4_096
MAX_QUERY_CHARS = 256
MAX_ROWS = 50
MAX_SQL_STEPS = 10_000
MAX_SQL_VALUE_BYTES = 4_096
MAX_SQL_CONTENT_BYTES = 1_024
MAX_SQL_METADATA_BYTES = 256
MAX_SQL_PROJECTION_ROWS = 128
MAX_SQL_PROJECTION_BYTES = 262_144
MONTY_VERSION = "0.0.21"
MONTY_WORKER_SHA256 = "bc4767743e5fb9fa360fbee21ded25e2642d8ad89a5c4f81b02a67d66c93a385"
MONTY_PACKAGE_RECORD_SHA256 = {
    "pydantic-monty": "39e9d51137276d783e5fce7df89b72077e53c3260ea391f4edcde7f6092a68ca",
    "pydantic-monty-client": "f925609bbf1c47f2002ed36367a6f7b7c88c1daf495a37ac24fdb9e240757f75",
    "pydantic-monty-runtime": "4eb88d6f850366a0d2a57c935bb50a6d736e2a3c961177cb8fa1d6384b0eee16",
}
_PROJECT_PYTHON = Path(__file__).resolve().parents[3] / ".venv" / "bin" / "python"
_EXPECTED_SOABI = "cpython-312-x86_64-linux-gnu"
_EXPECTED_LIBC = ("glibc", "2.43")
_EXPECTED_SQLITE_VERSION = "3.53.1"
E2E_WORKER_CRASH_SOURCE = "raise RuntimeError('__scroll_e2e_worker_crash__')"
_E2E_WORKER_CRASH_ENV = "HERMES_SCROLL_E2E_WORKER_CRASH"
_DATE_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")
_SQL_FORBIDDEN_RE = re.compile(
    r"\b(?:insert|update|delete|replace|merge|drop|alter|create|pragma|attach|detach|vacuum|reindex|analyze|load_extension)\b",
    re.IGNORECASE,
)
_SQL_ALLOWED_FUNCTIONS = frozenset({
    "abs", "avg", "coalesce", "count", "date", "datetime", "glob", "ifnull", "instr", "length",
    "like", "lower", "ltrim", "max", "min", "nullif", "round", "rtrim", "strftime", "substr", "sum",
    "total", "trim", "upper",
})


class ScrollReplError(RuntimeError):
    """A failed Monty cell with bounded output produced before the failure."""

    def __init__(self, cause: Exception, output: str) -> None:
        super().__init__(str(cause))
        self.output = output


def _package_record_matches_lock(package: str) -> bool:
    """Verify one installed wheel's locked RECORD and every recorded file."""
    try:
        distribution = importlib.metadata.distribution(package)
        if distribution.version != MONTY_VERSION:
            return False
        record = distribution.read_text("RECORD")
        if not record or hashlib.sha256(record.encode()).hexdigest() != MONTY_PACKAGE_RECORD_SHA256[package]:
            return False
        root = Path(distribution.locate_file("")).resolve()
        for row in csv.reader(record.splitlines()):
            if len(row) != 3:
                return False
            relative, digest, size = row
            if not relative or Path(relative).is_absolute():
                return False
            if not digest:
                if size or not relative.endswith(".dist-info/RECORD"):
                    return False
                continue
            if not size:
                return False
            algorithm, encoded = digest.split("=", 1)
            if algorithm != "sha256":
                return False
            candidate = (root / relative).resolve()
            worker = Path(sys.executable).with_name("monty").resolve()
            if candidate != worker and root not in (candidate, *candidate.parents):
                return False
            if not candidate.is_file():
                return False
            payload = candidate.read_bytes()
            actual = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode()
            if actual != encoded or len(payload) != int(size):
                return False
    except (FileNotFoundError, ImportError, KeyError, OSError, ValueError):
        return False
    return True


def locked_monty_available() -> bool:
    """Verify the exact local interpreter, package records, and worker before use."""
    if (
        sys.version_info[:3] != (3, 12, 14)
        or sys.implementation.name != "cpython"
        or platform.system() != "Linux"
        or platform.machine() != "x86_64"
        or platform.libc_ver() != _EXPECTED_LIBC
        or sqlite3.sqlite_version != _EXPECTED_SQLITE_VERSION
        or sysconfig.get_config_var("SOABI") != _EXPECTED_SOABI
        or Path(sys.executable) != _PROJECT_PYTHON
    ):
        return False
    if not all(_package_record_matches_lock(package) for package in MONTY_PACKAGE_RECORD_SHA256):
        return False
    worker = Path(sys.executable).with_name("monty")
    try:
        return worker.is_file() and hashlib.sha256(worker.read_bytes()).hexdigest() == MONTY_WORKER_SHA256
    except OSError:
        return False


BOOTSTRAP = """
class _ScrollMemorySpace:
    def search(self, query, scope="session", kind=None, k=10, snippet=True):
        return _scroll_search(query, scope, kind, k, snippet)

    def expand(self, seqs, code=False):
        return _scroll_expand(seqs, code)

    def sql_query(self, sql, params=()):
        return _scroll_sql_query(sql, params)

    def stats(self):
        return _scroll_stats()

ms = _ScrollMemorySpace()
ms.session_id = _scroll_session_id()
ms.task_id = _scroll_task_id()

def or_terms(terms):
    parts = []
    for raw in terms:
        term = str(raw).strip()
        if not term:
            continue
        if " " in term or "-" in term or "/" in term:
            parts.append('"' + term.replace('"', '') + '"')
        else:
            parts.append(term)
    return " OR ".join(parts)

def days_between(start, end, inclusive=False):
    return _scroll_days_between(start, end, inclusive)

def _scroll_digest_value(name, value):
    try:
        size = len(value)
    except Exception:
        size = None
    print(name + ":" + type(value).__name__ + ":" + str(size))
"""


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 3:
        raise ValueError("nested value exceeds the depth limit")
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite floats are not JSON-safe")
        return value
    if isinstance(value, str):
        if len(value) > 1_024:
            raise ValueError("string exceeds the size limit")
        return value
    if isinstance(value, (list, tuple)):
        if len(value) > 16:
            raise ValueError("sequence exceeds the item limit")
        return [_json_safe(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > 16 or not all(isinstance(key, str) for key in value):
            raise ValueError("mapping is not JSON-safe")
        return {key: _json_safe(item, depth=depth + 1) for key, item in value.items()}
    raise ValueError(f"unsupported value type: {type(value).__name__}")


def _sql_projection_text(value: Optional[str], limit: int) -> Optional[str]:
    if value is None:
        return None
    candidate = value[:limit]
    encoded = candidate.encode("utf-8")
    if len(encoded) <= limit:
        return candidate
    return encoded[:limit].decode("utf-8", "ignore")


def _parse_date(value: Any) -> date:
    match = _DATE_RE.search(str(value))
    if not match:
        raise ValueError("date must contain YYYY-MM-DD or YYYY/MM/DD")
    year, month, day = (int(part) for part in match.groups())
    return date(year, month, day)


class ScrollCallbacks:
    """Read-only callbacks over the host-projected snapshot, never storage."""

    def __init__(self, snapshot_getter: Callable[[], Optional[CanonicalHistorySnapshot]]) -> None:
        self._snapshot_getter = snapshot_getter
        self._stats = {"hist_search": 0, "hist_expand": 0, "hist_sql": 0}
        self._stale_sequences: set[int] = set()
        self._fts_available: Optional[bool] = None

    def rebind(self, snapshot: CanonicalHistorySnapshot, previous: Optional[CanonicalHistorySnapshot] = None) -> None:
        previous = previous if previous is not None else self._snapshot_getter()
        if previous is not None:
            if previous.lineage_id != snapshot.lineage_id or previous.generation != snapshot.generation:
                self._stale_sequences.update(row._row_id for row in previous.rows)
            else:
                current_ids = {row._row_id for row in snapshot.rows}
                self._stale_sequences.update(row._row_id for row in previous.rows if row._row_id not in current_ids)

    def _snapshot(self) -> CanonicalHistorySnapshot:
        snapshot = self._snapshot_getter()
        if snapshot is None:
            raise ValueError("canonical history is not available yet")
        return snapshot

    @staticmethod
    def _recallable_rows(snapshot: CanonicalHistorySnapshot) -> tuple[Any, ...]:
        """Exclude Scroll's own source and output from future recall queries."""
        return tuple(
            row for row in snapshot.rows
            if row.tool_name != "scroll_repl" and not any(call.name == "scroll_repl" for call in row.tool_calls)
        )

    def _sql_projection_rows(self, snapshot: CanonicalHistorySnapshot) -> Iterable[tuple[Any, ...]]:
        rows = []
        projected_bytes = 0
        for row in reversed(snapshot.rows):
            if row.tool_name == "scroll_repl" or any(call.name == "scroll_repl" for call in row.tool_calls):
                continue
            values = (
                row._row_id, row.generation, _sql_projection_text(row.session_id, MAX_SQL_METADATA_BYTES),
                _sql_projection_text(row.role, MAX_SQL_METADATA_BYTES), _sql_projection_text(row.text, MAX_SQL_CONTENT_BYTES),
                _sql_projection_text(row.tool_name, MAX_SQL_METADATA_BYTES),
                _sql_projection_text(row.tool_call_id, MAX_SQL_METADATA_BYTES), row.timestamp,
                int(row.is_compressed_summary), _sql_projection_text(row.sensitivity, MAX_SQL_METADATA_BYTES),
                _sql_projection_text(row.fidelity, MAX_SQL_METADATA_BYTES),
            )
            value_bytes = sum(len(value.encode("utf-8")) for value in values if isinstance(value, str))
            if len(rows) >= MAX_SQL_PROJECTION_ROWS or projected_bytes + value_bytes > MAX_SQL_PROJECTION_BYTES:
                break
            rows.append(values)
            projected_bytes += value_bytes
        return reversed(rows)

    def lookup(self) -> Dict[str, Callable[..., Any]]:
        return {
            "_scroll_search": self.search,
            "_scroll_expand": self.expand,
            "_scroll_sql_query": self.sql_query,
            "_scroll_stats": self.stats,
            "_scroll_session_id": self.session_id,
            "_scroll_task_id": self.task_id,
            "_scroll_days_between": self.days_between,
        }

    def session_id(self) -> str:
        snapshot = self._snapshot()
        return snapshot.rows[-1].session_id if snapshot.rows else snapshot.lineage_id

    def task_id(self) -> str:
        return self._snapshot().lineage_id

    def _fts_matches(self, candidates: list[tuple[Any, str]], terms: list[str]) -> Optional[set[int]]:
        """Return FTS matches, or ``None`` when SQLite must degrade to scanning."""
        if self._fts_available is False:
            return None
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE VIRTUAL TABLE recall_fts USING fts5(seq UNINDEXED, content)")
            conn.executemany("INSERT INTO recall_fts VALUES (?, ?)", [
                (row._row_id, haystack) for row, haystack in candidates
            ])
            query = " OR ".join('"' + term.replace('"', "") + '"' for term in terms)
            matches = {int(row[0]) for row in conn.execute("SELECT seq FROM recall_fts WHERE recall_fts MATCH ?", (query,))}
            self._fts_available = True
            return matches
        except sqlite3.DatabaseError:
            self._fts_available = False
            return None
        finally:
            conn.close()

    def search(self, query: Any, scope: Any = "session", kind: Any = None, k: Any = 10, snippet: Any = True) -> list[dict[str, Any]]:
        if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_CHARS:
            raise ValueError("query must be a non-empty bounded string")
        if scope not in {"session", "task", "all"} or not isinstance(k, int) or not 1 <= k <= 10:
            raise ValueError("invalid search request")
        if kind is not None and (not isinstance(kind, str) or len(kind) > 64):
            raise ValueError("invalid kind")
        snapshot = self._snapshot()
        current_session = self.session_id()
        terms = [term.casefold() for term in re.findall(r"[\w-]+", query) if term]
        candidates = []
        for row in self._recallable_rows(snapshot):
            if scope == "session" and row.session_id != current_session:
                continue
            row_kind = "tool_result" if row.role == "tool" else row.role
            if kind is not None and row_kind != kind:
                continue
            candidates.append((row, " ".join((row.text, row.tool_name or "", row.role)).casefold()))
        fts_matches = self._fts_matches(candidates, terms)
        rows = []
        for row, haystack in candidates:
            row_kind = "tool_result" if row.role == "tool" else row.role
            if fts_matches is not None and row._row_id not in fts_matches:
                continue
            score = sum(term in haystack for term in terms)
            if score:
                content = row.text
                if bool(snippet) and len(content) > 300:
                    content = content[:300].rstrip() + "…"
                rows.append({
                    "seq": row._row_id, "generation": row.generation, "role": row.role,
                    "kind": row_kind, "name": row.tool_name, "content": content,
                    "score": score, "fidelity": row.fidelity,
                })
        rows.sort(key=lambda item: (-item["score"], item["seq"]))
        self._stats["hist_search"] += 1
        results = rows[:k]
        self._stale_sequences.difference_update(row["seq"] for row in results)
        return _json_safe(results)

    def expand(self, seqs: Any, code: Any = False) -> list[dict[str, Any]]:
        values = _json_safe(seqs)
        if isinstance(values, int):
            values = [values]
        if not isinstance(values, list) or not all(isinstance(seq, int) and seq >= 0 for seq in values):
            raise ValueError("seqs must be bounded non-negative integers")
        if any(seq in self._stale_sequences for seq in values):
            raise ValueError("stale sequence handle; refresh search results")
        snapshot = self._snapshot()
        by_seq = {row._row_id: row for row in self._recallable_rows(snapshot)}
        rows = []
        for seq in values:
            row = by_seq.get(seq)
            if row is None:
                continue
            rows.append({
                "seq": row._row_id, "generation": row.generation, "role": row.role,
                "kind": "tool_result" if row.role == "tool" else row.role,
                "name": row.tool_name, "content": row.text, "code": bool(code) and False,
                "fidelity": row.fidelity, "is_compressed_summary": row.is_compressed_summary,
            })
        self._stats["hist_expand"] += 1
        return _json_safe(rows)

    @staticmethod
    def _validate_sql(sql: Any, params: Any) -> Tuple[str, Any]:
        if not isinstance(sql, str) or len(sql) > 2_048:
            raise ValueError("sql must be a bounded string")
        statement = sql.strip()
        if ";" in statement or "--" in statement or "/*" in statement:
            raise ValueError("sql must contain exactly one comment-free statement")
        if not re.match(r"^(?:select|with)\b", statement, re.IGNORECASE) or _SQL_FORBIDDEN_RE.search(statement):
            raise ValueError("only one read-only SELECT or CTE is allowed")
        if not re.search(r"\bhistory\b", statement, re.IGNORECASE):
            raise ValueError("sql may query only the fixed history schema")
        if params is None:
            return statement, ()
        safe_params = _json_safe(params)
        if not isinstance(safe_params, (list, dict)):
            raise ValueError("params must be a bounded sequence or mapping")
        values: Iterable[Any] = safe_params.values() if isinstance(safe_params, dict) else safe_params
        for value in values:
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("params must contain finite scalar values")
            if not isinstance(value, (type(None), bool, int, float, str)):
                raise ValueError("params must contain only bounded scalar values")
        return statement, safe_params

    def sql_query(self, sql: Any, params: Any = ()) -> list[dict[str, Any]]:
        statement, bindings = self._validate_sql(sql, params)
        snapshot = self._snapshot()
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(
                """CREATE TABLE history (
                       seq INTEGER PRIMARY KEY, generation INTEGER NOT NULL, session_id TEXT NOT NULL,
                       role TEXT NOT NULL, content TEXT NOT NULL, tool_name TEXT, tool_call_id TEXT,
                       timestamp REAL, is_compressed_summary INTEGER NOT NULL, sensitivity TEXT NOT NULL,
                       fidelity TEXT NOT NULL
                   )"""
            )
            conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_SQL_VALUE_BYTES)
            conn.executemany(
                "INSERT INTO history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._sql_projection_rows(snapshot),
            )
            conn.execute("PRAGMA query_only = ON")
            read_history = False

            def _authorizer(
                action: int, arg1: Optional[str], arg2: Optional[str], db: Optional[str], _source: Optional[str],
            ) -> int:
                nonlocal read_history
                if action == sqlite3.SQLITE_READ:
                    if db not in {None, "main"} or arg1 != "history":
                        return sqlite3.SQLITE_DENY
                    read_history = True
                if action == sqlite3.SQLITE_FUNCTION:
                    return sqlite3.SQLITE_OK if (arg2 or "").casefold() in _SQL_ALLOWED_FUNCTIONS else sqlite3.SQLITE_DENY
                if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ}:
                    return sqlite3.SQLITE_OK
                return sqlite3.SQLITE_DENY

            conn.set_authorizer(_authorizer)
            remaining = MAX_SQL_STEPS

            def _progress() -> int:
                nonlocal remaining
                remaining -= 100
                return int(remaining <= 0)

            conn.set_progress_handler(_progress, 100)
            result = []
            for index, row in enumerate(conn.execute(statement, bindings)):
                if index >= MAX_ROWS:
                    result.append({"_truncated": True, "_row_cap": MAX_ROWS})
                    break
                result.append({key: row[key] for key in row.keys()})
            if not read_history:
                raise ValueError("sql must read the fixed history table")
            self._stats["hist_sql"] += 1
            return [_json_safe(row) for row in result]
        finally:
            conn.close()

    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    def days_between(self, start: Any, end: Any, inclusive: Any = False) -> int:
        if not isinstance(inclusive, bool):
            raise ValueError("inclusive must be a boolean")
        days = abs((_parse_date(end) - _parse_date(start)).days)
        return days + 1 if inclusive else days


class MontyScrollRepl:
    """One serialized checkout, deliberately discarded at lifecycle boundaries."""

    _LIMITS = {"max_duration_secs": 1.0, "max_memory": 16 * 1024 * 1024, "max_recursion_depth": 100}

    def __init__(self, callbacks: ScrollCallbacks) -> None:
        self._callbacks = callbacks
        self._pool = None
        self._checkout = None
        self._session = None
        self._lock = threading.RLock()
        self._digest_names: list[str] = []

    @staticmethod
    def _source_names(source: str) -> tuple[set[str], set[str]]:
        """Return bounded-digest candidates without inspecting the checkout."""
        try:
            tree = ast.parse(source, mode="exec")
        except SyntaxError:
            return set(), set()
        assigned, deleted = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                assigned.add(node.name)
            elif isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Store):
                    assigned.add(node.id)
                elif isinstance(node.ctx, ast.Del):
                    deleted.add(node.id)
        return assigned, deleted

    def _remember_names(self, source: str) -> None:
        assigned, deleted = self._source_names(source)
        for name in deleted:
            if name in self._digest_names:
                self._digest_names.remove(name)
        for name in sorted(assigned - {"ms", "or_terms"}):
            if name in self._digest_names:
                self._digest_names.remove(name)
            self._digest_names.append(name)
        del self._digest_names[:-16]

    def _ensure_session(self) -> Any:
        if self._session is not None:
            return self._session
        if not locked_monty_available():
            raise RuntimeError("locked Monty runtime verification failed")
        from pydantic_monty import Monty

        self._pool = Monty(min_processes=1, max_processes=1, request_timeout=2.0)
        self._pool.__enter__()
        self._checkout = self._pool.checkout(limits=self._LIMITS)
        self._session = self._checkout.__enter__()
        return self._session

    @staticmethod
    def _terminate_worker_for_e2e_test(session: Any) -> None:
        if os.environ.get(_E2E_WORKER_CRASH_ENV) == "1":
            os.kill(session.worker_pid, signal.SIGKILL)

    def run(self, source: str) -> str:
        if not isinstance(source, str) or not source.strip() or len(source) > MAX_SOURCE_CHARS:
            raise ValueError("source must be a non-empty string up to 4096 characters")
        from pydantic_monty import CollectString

        with self._lock:
            output = CollectString(max_bytes=MAX_OUTPUT_BYTES)
            session = self._ensure_session()
            try:
                if source == E2E_WORKER_CRASH_SOURCE:
                    self._terminate_worker_for_e2e_test(session)
                session.feed_run(BOOTSTRAP + "\n" + source, external_lookup=self._callbacks.lookup(), print_callback=output)
            except Exception as exc:
                raise ScrollReplError(exc, output.output) from exc
            self._remember_names(source)
            return output.output

    def working_memory_digest(self) -> str:
        """Return only resident variable names, types, and bounded shapes."""
        from pydantic_monty import CollectString

        with self._lock:
            if self._session is None or not self._digest_names:
                return ""
            source = "\n".join(
                line for name in self._digest_names
                for line in ("try:", f"    _scroll_digest_value({name!r}, {name})", "except Exception:", "    pass")
            )
            output = CollectString(max_bytes=1_024)
            try:
                self._session.feed_run(BOOTSTRAP + "\n" + source, external_lookup=self._callbacks.lookup(), print_callback=output)
            except Exception as exc:
                raise ScrollReplError(exc, output.output) from exc
            return output.output

    def close(self) -> None:
        with self._lock:
            checkout, pool = self._checkout, self._pool
            self._checkout = self._pool = self._session = None
            self._digest_names = []
            if checkout is not None:
                checkout.__exit__(None, None, None)
            if pool is not None:
                pool.__exit__(None, None, None)
