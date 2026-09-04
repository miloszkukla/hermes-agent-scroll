"""Redacted, rebuildable Scroll cache files with conservative POSIX hardening."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

from agent.context_engine import CanonicalHistorySnapshot


CACHE_SCHEMA_VERSION = 1
SCROLL_SOURCE_COMMIT = "313077708ea105cc79bf0a997338e14dae916f8c"
MONTY_LOCK = "pydantic-monty=0.0.21,pydantic-monty-client=0.0.21,pydantic-monty-runtime=0.0.21"
NORMALIZATION_VERSION = 1


def _fingerprint() -> str:
    value = {
        "cache_schema": CACHE_SCHEMA_VERSION,
        "monty_lock": MONTY_LOCK,
        "normalization": NORMALIZATION_VERSION,
        "scroll_commit": SCROLL_SOURCE_COMMIT,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class ScrollCache:
    """Store only canonical value projections; failures are safe cache misses."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _lineage_file(self, lineage_id: str) -> Path:
        digest = hashlib.sha256(lineage_id.encode("utf-8", errors="replace")).hexdigest()
        return self._root / f"{digest}.json"

    def _prepare_root(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self._root.is_symlink() or not self._root.is_dir():
            raise OSError("Scroll cache root is not a real directory")
        os.chmod(self._root, 0o700)

    @contextmanager
    def _locked(self, lineage_id: str):
        """Serialize same-lineage cache replacement across Linux processes."""
        import fcntl

        self._prepare_root()
        lock_path = self._lineage_file(lineage_id).with_suffix(".lock")
        if lock_path.is_symlink():
            raise OSError("Scroll cache lock is a symlink")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(lock_path, flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def acquire_owner(self, lineage_id: str) -> Optional[int]:
        """Claim one non-blocking process lease for a logical lineage."""
        import fcntl

        self._prepare_root()
        lock_path = self._lineage_file(lineage_id).with_suffix(".owner.lock")
        if lock_path.is_symlink():
            raise OSError("Scroll cache owner lock is a symlink")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(lock_path, flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return None
        except Exception:
            os.close(fd)
            raise
        return fd

    @staticmethod
    def release_owner(fd: Optional[int]) -> None:
        if fd is None:
            return
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    @staticmethod
    def _payload(snapshot: CanonicalHistorySnapshot) -> dict[str, Any]:
        return {
            "version": CACHE_SCHEMA_VERSION,
            "fingerprint": _fingerprint(),
            "lineage_id": snapshot.lineage_id,
            "generation": snapshot.generation,
            "high_water_mark": snapshot.high_water_mark,
            "rows": [{
                "row_id": row._row_id,
                "generation": row.generation,
                "order_key": row.order_key,
                "session_id": row.session_id,
                "role": row.role,
                "text": row.text,
                "content_reference": row.content_reference,
                "tool_name": row.tool_name,
                "tool_call_id": row.tool_call_id,
                "tool_calls": [{
                    "name": call.name, "call_id": call.call_id, "arguments_digest": call.arguments_digest,
                } for call in row.tool_calls],
                "correlation": row.correlation,
                "timestamp": row.timestamp,
                "sensitivity": row.sensitivity,
                "fidelity": row.fidelity,
                "is_compressed_summary": row.is_compressed_summary,
            } for row in snapshot.rows],
        }

    def store(self, snapshot: CanonicalHistorySnapshot) -> None:
        with self._locked(snapshot.lineage_id):
            target = self._lineage_file(snapshot.lineage_id)
            if target.is_symlink():
                raise OSError("Scroll cache target is a symlink")
            encoded = json.dumps(self._payload(snapshot), sort_keys=True, separators=(",", ":")).encode("utf-8")
            fd, temporary = tempfile.mkstemp(prefix=".scroll-", suffix=".tmp", dir=self._root)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
                os.chmod(target, 0o600)
                directory_fd = os.open(self._root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                try:
                    Path(temporary).unlink(missing_ok=True)
                except OSError:
                    pass

    def load_metadata(self, lineage_id: str) -> Optional[dict[str, Any]]:
        try:
            with self._locked(lineage_id):
                target = self._lineage_file(lineage_id)
                if target.is_symlink() or not target.is_file():
                    return None
                fd = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                try:
                    if not stat.S_ISREG(os.fstat(fd).st_mode):
                        return None
                    with os.fdopen(fd, "r", encoding="utf-8") as handle:
                        fd = -1
                        value = json.load(handle)
                finally:
                    if fd >= 0:
                        os.close(fd)
            if (
                not isinstance(value, dict)
                or value.get("version") != CACHE_SCHEMA_VERSION
                or value.get("fingerprint") != _fingerprint()
                or value.get("lineage_id") != lineage_id
            ):
                return None
            if not isinstance(value.get("generation"), int) or not isinstance(value.get("high_water_mark"), int):
                return None
            return value
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def delete(self, lineage_id: str) -> None:
        """Remove one rebuildable lineage cache without following a symlink."""
        with self._locked(lineage_id):
            target = self._lineage_file(lineage_id)
            if target.is_symlink():
                raise OSError("Scroll cache target is a symlink")
            target.unlink(missing_ok=True)
