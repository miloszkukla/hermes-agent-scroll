"""Fixture runner for the credential-free Scroll recall evidence lane."""

from __future__ import annotations

from typing import Any

from .fixtures import FIXTURES, ScrollFixture, snapshot_for
from plugins.context_engine.scroll.sandbox import ScrollCallbacks


def run_fixture(fixture: ScrollFixture) -> dict[str, Any]:
    snapshot = snapshot_for(fixture)
    callbacks = ScrollCallbacks(lambda: snapshot)
    callbacks.rebind(snapshot)
    hits = callbacks.search(fixture.query, scope="all", k=10, snippet=False)
    expanded = callbacks.expand([hit["seq"] for hit in hits])
    recovered = "\n".join(row["content"] for row in expanded)
    return {
        "fixture": fixture.identifier,
        "ok": fixture.required_text.casefold() in recovered.casefold(),
        "matches": len(hits),
        "stats": callbacks.stats(),
    }


def run_all() -> list[dict[str, Any]]:
    return [run_fixture(fixture) for fixture in FIXTURES]
