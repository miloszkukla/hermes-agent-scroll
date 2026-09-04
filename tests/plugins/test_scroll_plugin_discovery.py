"""Scroll discovery must be independent of the current directory and vendor name."""

from plugins.context_engine import discover_context_engines, load_context_engine
from plugins.context_engine.scroll.engine import ScrollContextEngine


def test_scroll_context_engine_loads_from_a_non_repository_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    discovered = {name: available for name, _description, available in discover_context_engines()}
    engine = load_context_engine("scroll")

    assert discovered["scroll"] is True
    assert isinstance(engine, ScrollContextEngine)
    assert type(engine).__module__ == "plugins.context_engine.scroll.engine"
    assert [schema["name"] for schema in engine.get_tool_schemas()] == ["scroll_repl"]
    engine.on_session_end("session", [])
