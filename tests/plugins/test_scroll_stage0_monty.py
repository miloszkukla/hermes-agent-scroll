"""Pinned Monty stop/go evidence for the sandboxed Scroll integration."""

from __future__ import annotations

import hashlib
import importlib.metadata
import math
import platform
import re
import sqlite3
import sys
import sysconfig
from pathlib import Path
from typing import Any

import pytest
import psutil
from pydantic_monty import CollectString, Monty, MontyConversionError, MontyCrashedError, MontyError, MontyRuntimeError
from agent.context_engine import CanonicalHistoryRow, CanonicalHistorySnapshot
from plugins.context_engine.scroll import sandbox
from plugins.context_engine.scroll.sandbox import MontyScrollRepl, ScrollCallbacks, locked_monty_available


_MONTY_VERSION = "0.0.21"
_WORKER_SHA256 = "bc4767743e5fb9fa360fbee21ded25e2642d8ad89a5c4f81b02a67d66c93a385"
_LIMITS = {"max_duration_secs": 1.0, "max_memory": 16 * 1024 * 1024, "max_recursion_depth": 100}
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

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
        if len(value) > 1024:
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


class _ReadOnlyCallbacks:
    def search(self, query: Any, scope: Any, kind: Any, k: Any, snippet: Any) -> list[dict[str, Any]]:
        if not isinstance(query, str) or len(query) > 256:
            raise ValueError("query must be a bounded string")
        if scope not in {"session", "task", "all"} or kind not in {None, "user"} or not isinstance(k, int) or not 1 <= k <= 10:
            raise ValueError("invalid search request")
        return _json_safe([{"seq": 7, "content": query, "scope": scope, "kind": kind, "k": k, "snippet": bool(snippet)}])

    def expand(self, seqs: Any, code: Any) -> list[dict[str, Any]]:
        values = _json_safe(seqs)
        if not isinstance(values, list) or not all(isinstance(seq, int) and seq >= 0 for seq in values):
            raise ValueError("seqs must be bounded non-negative integers")
        return _json_safe([{"seq": seq, "code": bool(code)} for seq in values])

    def sql_query(self, sql: Any, params: Any) -> list[dict[str, Any]]:
        if not isinstance(sql, str) or not sql.lstrip().lower().startswith(("select", "with")):
            raise ValueError("only a read-only SELECT or CTE is allowed")
        return _json_safe([{"sql": sql, "params": _json_safe(params)}])

    def stats(self) -> dict[str, int]:
        return {"hist_fts": 1, "hist_seq": 2, "hist_scan": 0}

    def days_between(self, start: Any, end: Any, inclusive: Any) -> int:
        if (start, end) != ("2024-01-01", "2024-01-03"):
            raise ValueError("unexpected date request")
        return 3 if inclusive else 2

    def lookup(self) -> dict[str, Any]:
        return {
            "_scroll_search": self.search,
            "_scroll_expand": self.expand,
            "_scroll_sql_query": self.sql_query,
            "_scroll_stats": self.stats,
            "_scroll_session_id": lambda: "session-opaque",
            "_scroll_task_id": lambda: "task-opaque",
            "_scroll_days_between": self.days_between,
        }


class _StageZeroRepl:
    def __init__(self, session) -> None:
        self._callbacks = _ReadOnlyCallbacks()
        self._session = session

    def run(self, source: str, *, max_bytes: int = 4096) -> str:
        if len(source) > 4096:
            raise ValueError("source exceeds the Stage 0 input limit")
        output = CollectString(max_bytes=max_bytes)
        self._session.feed_run(sandbox.BOOTSTRAP + "\n" + source, external_lookup=self._callbacks.lookup(), print_callback=output)
        return output.output

    def digest(self, names: tuple[str, ...]) -> str:
        if len(names) > 16 or not all(_IDENTIFIER_RE.fullmatch(name) for name in names):
            raise ValueError("digest names must be bounded Python identifiers")
        lines = []
        for name in names:
            lines.extend(("try:", f"    _scroll_digest_value({name!r}, {name})", "except Exception:", "    pass"))
        return self.run("\n".join(lines), max_bytes=1024)


@pytest.fixture
def repl():
    with Monty(min_processes=1, max_processes=1, request_timeout=2.0) as pool:
        with pool.checkout(limits=_LIMITS) as session:
            yield _StageZeroRepl(session)


def test_stage_zero_locked_runtime_identity() -> None:
    assert sys.version_info[:3] == (3, 12, 14)
    assert Path(sys.executable) == Path(__file__).resolve().parents[2] / ".venv" / "bin" / "python"
    assert sys.implementation.name == "cpython"
    assert sysconfig.get_config_var("SOABI") == "cpython-312-x86_64-linux-gnu"
    assert platform.system() == "Linux"
    assert platform.machine() == "x86_64"
    assert platform.libc_ver() == ("glibc", "2.43")
    assert sqlite3.sqlite_version == "3.53.1"
    assert locked_monty_available() is True
    for package in ("pydantic-monty", "pydantic-monty-client", "pydantic-monty-runtime"):
        assert importlib.metadata.version(package) == _MONTY_VERSION
    worker = Path(sys.executable).with_name("monty")
    assert worker.is_file()
    assert hashlib.sha256(worker.read_bytes()).hexdigest() == _WORKER_SHA256


def test_stage_zero_rejects_a_runtime_identity_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox.platform, "libc_ver", lambda: ("glibc", "2.42"))

    assert locked_monty_available() is False


def test_stage_zero_rejects_a_sqlite_identity_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox.sqlite3, "sqlite_version", "3.53.0")

    assert locked_monty_available() is False


def test_stage_zero_rejects_a_package_record_digest_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sandbox.MONTY_PACKAGE_RECORD_SHA256, "pydantic-monty", "0" * 64)

    assert locked_monty_available() is False


def test_stage_zero_worker_drops_the_host_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCROLL_STAGE0_INHERIT_SENTINEL", "present")
    with Monty(min_processes=1, max_processes=1, request_timeout=2.0) as pool:
        workers = [child for child in psutil.Process().children(recursive=True) if child.name() == "monty"]
        assert len(workers) == 1
        assert "SCROLL_STAGE0_INHERIT_SENTINEL" not in workers[0].environ()


def test_stage_zero_protocol_persistence_rebinding_and_bounded_digest(repl: _StageZeroRepl) -> None:
    output = repl.run(
        "values = [number * number for number in range(5)]\n"
        "def score(rows):\n"
        "    return sum(row['seq'] for row in rows)\n"
        "hits = ms.search('needle', 'task', k=3)\n"
        "print(score(hits), values[-1], ms.session_id, ms.task_id, ms.stats()['hist_seq'])\n"
        "print(days_between('2024-01-01', '2024-01-03'), or_terms(['module', 'message-passing', 'event driven']))\n"
        "42"
    )
    assert output == '7 16 session-opaque task-opaque 2\n2 module OR "message-passing" OR "event driven"\n'
    assert repl.run("ms = 'shadowed'\nor_terms = 'shadowed'\nprint(values[3])") == "9\n"
    assert repl.run("print(ms.expand([7], True)[0]['code'], or_terms(['again', 'event driven']))") == 'True again OR "event driven"\n'
    assert repl.digest(("values", "hits", "missing")) == "values:list:5\nhits:list:1\n"
    with pytest.raises(MontyRuntimeError, match="nested value exceeds the depth limit"):
        repl.run("ms.sql_query('SELECT 1', [[[[[1]]]]])")
    with pytest.raises(ValueError, match="unsupported value type"):
        _json_safe(object())


def test_stage_zero_production_wrapper_uses_the_deployed_bootstrap_and_callbacks() -> None:
    snapshot = CanonicalHistorySnapshot("lineage", 1, 7, (
        CanonicalHistoryRow(
            _row_id=7, generation=1, order_key=(1, 7), session_id="session", role="user",
            text="needle detail", content_reference=None, tool_name=None, tool_call_id=None,
            tool_calls=(), correlation=(), timestamp=None, sensitivity="normal", fidelity="text",
            is_compressed_summary=False,
        ),
    ))
    repl = MontyScrollRepl(ScrollCallbacks(lambda: snapshot))
    try:
        assert repl.run("values = [number * number for number in range(5)]\nhits = ms.search('needle', scope='task', kind='user', k=3)\nprint(hits[0]['seq'], values[-1])") == "7 16\n"
        assert repl.run("ms = 'shadowed'\nprint(values[3])") == "9\n"
        assert repl.run("print(ms.expand([7])[0]['content'], or_terms(['event driven']))") == 'needle detail "event driven"\n'
        assert repl.working_memory_digest() == "hits:list:1\nvalues:list:5\n"
    finally:
        repl.close()


@pytest.mark.parametrize(
    ("source", "limits", "expected"),
    [
        ("while True:\n    pass", {"max_duration_secs": 0.05, "max_memory": 16 * 1024 * 1024, "max_recursion_depth": 100}, "time limit exceeded"),
        ("blob = 'x' * (64 * 1024 * 1024)", {"max_duration_secs": 1.0, "max_memory": 2 * 1024 * 1024, "max_recursion_depth": 100}, "memory limit exceeded"),
        ("def descend(n):\n    return descend(n + 1)\ndescend(0)", {"max_duration_secs": 1.0, "max_memory": 16 * 1024 * 1024, "max_recursion_depth": 20}, "maximum recursion depth exceeded"),
        ("print('x' * 4096)", _LIMITS, "memory limit exceeded"),
    ],
)
def test_stage_zero_resource_limits(source: str, limits: dict[str, int | float], expected: str) -> None:
    with Monty(min_processes=1, max_processes=1, request_timeout=2.0) as pool:
        with pool.checkout(limits=limits) as session:
            with pytest.raises(MontyRuntimeError, match=expected):
                session.feed_run(source, print_callback=CollectString(max_bytes=256))


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("open('/etc/passwd').read()", "Permission denied"),
        ("import os\nos.environ", "not supported"),
        ("import socket\nsocket.socket()", "No module named 'socket'"),
        ("import subprocess\nsubprocess.run(['true'])", "No module named 'subprocess'"),
        ("object.__subclasses__()", "name 'object' is not defined"),
    ],
)
def test_stage_zero_denies_ambient_capabilities(source: str, expected: str) -> None:
    with Monty(min_processes=1, max_processes=1, request_timeout=2.0) as pool:
        with pool.checkout(limits=_LIMITS) as session:
            with pytest.raises(MontyRuntimeError, match=expected):
                session.feed_run(source)


def test_stage_zero_rejects_raw_host_object_serialization() -> None:
    with Monty(min_processes=1, max_processes=1, request_timeout=2.0) as pool:
        with pool.checkout(limits=_LIMITS) as session:
            with pytest.raises(MontyConversionError):
                session.feed_run("host_object", external_lookup={"host_object": object()})


def test_stage_zero_watchdog_replaces_only_the_worker() -> None:
    with Monty(min_processes=1, max_processes=1, request_timeout=0.1) as pool:
        with pytest.raises(MontyCrashedError) as crashed:
            with pool.checkout(limits={"max_memory": 16 * 1024 * 1024, "max_recursion_depth": 100}) as session:
                session.feed_run("while True:\n    pass")
        assert crashed.value.timed_out is True
        with pool.checkout(limits=_LIMITS) as replacement:
            assert replacement.feed_run("40 + 2") == 42
