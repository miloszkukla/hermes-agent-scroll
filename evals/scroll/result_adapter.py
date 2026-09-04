"""Stable, credential-free result rows shared by stock/plugin eval drivers."""

from __future__ import annotations

from typing import Any


RESULT_SCHEMA_VERSION = 1


def normalize_result(arm: str, result: dict[str, Any]) -> dict[str, Any]:
    if arm not in {"stock", "scroll"}:
        raise ValueError("arm must be stock or scroll")
    if not isinstance(result.get("fixture"), str) or not isinstance(result.get("ok"), bool):
        raise ValueError("result must include fixture and boolean ok")
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "arm": arm,
        "fixture": result["fixture"],
        "ok": result["ok"],
        "matches": int(result.get("matches", 0)),
        "stats": dict(result.get("stats") or {}),
    }
