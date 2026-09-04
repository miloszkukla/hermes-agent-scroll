"""Keep Scroll's user-facing enablement and local links executable enough to trust."""

from pathlib import Path

import yaml


_ROOT = Path(__file__).resolve().parents[2]
_SCROLL_DOCS = _ROOT / "plugins" / "context_engine" / "scroll"


def test_scroll_configuration_examples_parse_and_locked_command_is_local():
    readme = (_SCROLL_DOCS / "README.md").read_text(encoding="utf-8")
    configuration = (_ROOT / "website" / "docs" / "user-guide" / "configuration.md").read_text(encoding="utf-8")
    example = 'context:\n  engine: "scroll"\n'

    assert yaml.safe_load(example) == {"context": {"engine": "scroll"}}
    assert f"```yaml\n{example}```" in readme
    assert f"```yaml\n{example}```" in configuration
    bootstrap = _ROOT / "scripts" / "bootstrap_scroll_runtime.sh"
    assert "scripts/bootstrap_scroll_runtime.sh" in readme
    assert bootstrap.is_file()
    assert bootstrap.stat().st_mode & 0o111
    script = bootstrap.read_text(encoding="utf-8")
    assert "ec7a99cd05e0cd7f80243f135ce1361c76835cb0ee60055d14d20eba8eba1460" in script
    assert "72748da13197c1fb161e3afeef20a6a385ff24f2165e6e2758e47008e7faba4c" in script


def test_scroll_plugin_document_links_and_evaluation_commands_are_present():
    readme = (_SCROLL_DOCS / "README.md").read_text(encoding="utf-8")
    evaluation = (_SCROLL_DOCS / "EVALUATION.md").read_text(encoding="utf-8")
    model_preflight = (_SCROLL_DOCS / "evidence" / "MODEL-ACCESS-PREFLIGHT.md").read_text(encoding="utf-8")

    for name in ("UPSTREAM.md", "SECURITY.md", "SBOM.md", "EVALUATION.md"):
        assert f"]({name})" in readme
        assert (_SCROLL_DOCS / name).is_file()
    assert "tests/plugins/test_scroll_context_engine.py" in evaluation
    assert "scripts/run_tests.sh plugins/context_engine/scroll/vendor/tests" in evaluation
    assert "](evidence/MODEL-ACCESS-PREFLIGHT.md)" in evaluation
    assert "tests/evals/test_scroll_coding_trajectories.py" in evaluation
    assert "python -m evals.scroll.hermes_live" in evaluation
    assert "python -m evals.scroll.coding_live" in evaluation
    assert "do **not** require Qwen" in model_preflight
