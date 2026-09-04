"""Credential-free canonical-history fixtures for Scroll's deterministic lane."""

from __future__ import annotations

from dataclasses import dataclass

from agent.context_engine import CanonicalHistoryRow, CanonicalHistorySnapshot


@dataclass(frozen=True)
class ScrollFixture:
    identifier: str
    query: str
    required_text: str
    rows: tuple[tuple[str, str], ...]


FIXTURES = (
    ScrollFixture("temporal-update", "deployment timeout", "45 seconds", (("user", "set deployment timeout to 30 seconds"), ("assistant", "updated deployment timeout to 45 seconds"))),
    ScrollFixture("conflicting-evidence", "release channel", "stable channel", (("assistant", "use beta channel for the trial"), ("assistant", "final decision: use stable channel"))),
    ScrollFixture("dispersed-aggregation", "owner", "Rin", (("user", "database owner is Rin"), ("tool", "cache owner is Maya"), ("assistant", "Rin owns the database migration"))),
    ScrollFixture("exact-value", "build number", "build 4821", (("assistant", "the approved artifact is build 4821"),)),
    ScrollFixture("parallel-tool-groups", "parallel results", "both checks passed", (("assistant", "parallel results: both checks passed"),)),
    ScrollFixture("failed-retried-tools", "retry succeeded", "retry succeeded", (("tool", "first deploy failed"), ("tool", "retry succeeded with a clean migration"))),
    ScrollFixture("cache-loss-resume", "resume token", "resume token amber", (("assistant", "resume token amber was persisted before restart"),)),
    ScrollFixture("corruption-fallback", "rebuild source", "canonical snapshot", (("assistant", "cache corruption rebuild source is the canonical snapshot"),)),
)


def snapshot_for(fixture: ScrollFixture) -> CanonicalHistorySnapshot:
    rows = tuple(
        CanonicalHistoryRow(
            _row_id=index, generation=1, order_key=(1, index), session_id="fixture",
            role=role, text=text, content_reference=None, tool_name=None, tool_call_id=None,
            tool_calls=(), correlation=(), timestamp=float(index), sensitivity="normal",
            fidelity="text", is_compressed_summary=False,
        )
        for index, (role, text) in enumerate(fixture.rows, start=1)
    )
    return CanonicalHistorySnapshot("scroll-deterministic", 1, len(rows), rows)
