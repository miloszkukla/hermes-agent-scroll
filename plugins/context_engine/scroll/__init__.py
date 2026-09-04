"""Monty-only Scroll context engine."""

from .engine import ScrollContextEngine


def register(ctx) -> None:
    ctx.register_context_engine(ScrollContextEngine())


__all__ = ["ScrollContextEngine", "register"]
