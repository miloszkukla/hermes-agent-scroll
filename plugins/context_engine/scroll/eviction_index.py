"""Pure, bounded rendering of Scroll's model-authored eviction map."""

from __future__ import annotations

from dataclasses import dataclass


_LEVEL_CAP = 5
_NO_HEADLINE = "(no model-authored headline)"


@dataclass(frozen=True)
class Leaf:
    seq: int
    headline: str


@dataclass(frozen=True)
class Line:
    seq_lo: int
    seq_hi: int
    head: str
    tail: str

    @property
    def text(self) -> str:
        return self.head if self.head == self.tail else f"{self.head} - {self.tail}"

    @property
    def span(self) -> str:
        return f"seq {self.seq_lo}" if self.seq_lo == self.seq_hi else f"seq {self.seq_lo}–{self.seq_hi}"


@dataclass(frozen=True)
class Block:
    seq_lo: int
    seq_hi: int
    lines: tuple[Line, ...]

    @property
    def first(self) -> str:
        return self.lines[0].head if self.lines else _NO_HEADLINE

    @property
    def last(self) -> str:
        return self.lines[-1].tail if self.lines else _NO_HEADLINE


def _collapse(blocks: list[Block]) -> Block:
    return Block(
        min(block.seq_lo for block in blocks), max(block.seq_hi for block in blocks),
        tuple(Line(block.seq_lo, block.seq_hi, block.first, block.last) for block in blocks),
    )


class EvictionIndex:
    """A fresh, deterministic odometer index over omitted canonical rows."""

    def __init__(self, level_cap: int = _LEVEL_CAP) -> None:
        if level_cap < 3:
            raise ValueError("level_cap must be at least three")
        self._level_cap = level_cap
        self._levels: list[list[Block]] = []

    @property
    def is_empty(self) -> bool:
        return not any(self._levels)

    def add_eviction(self, leaves: list[Leaf], *, seq_lo: int, seq_hi: int) -> None:
        if seq_lo > seq_hi:
            raise ValueError("sequence range is invalid")
        if not self._levels:
            self._levels.append([])
        self._levels[0].append(Block(
            seq_lo, seq_hi, tuple(Line(leaf.seq, leaf.seq, leaf.headline, leaf.headline) for leaf in leaves),
        ))
        self._carry(0)

    def _carry(self, level: int) -> None:
        while len(self._levels[level]) >= self._level_cap:
            *older, newest = self._levels[level]
            self._levels[level] = [newest]
            if level + 1 == len(self._levels):
                self._levels.append([])
            self._levels[level + 1].append(_collapse(older))
            level += 1

    def render(self) -> list[str]:
        lines = []
        for level in range(len(self._levels) - 1, -1, -1):
            for block in self._levels[level]:
                lines.append(f"[L{level}] seq {block.seq_lo}–{block.seq_hi}")
                lines.extend(f"  · {line.span}  ⟦ {line.text} ⟧" for line in block.lines)
        return lines
