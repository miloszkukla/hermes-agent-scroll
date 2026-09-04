#!/usr/bin/env bash
# Run the exact pinned Scroll evaluation suite from a separately checked-out source tree.
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: bash scripts/run_scroll_upstream_evaluation_tests.sh <scroll-source-root> [pytest args...]" >&2
    exit 2
fi

source_root=$1
shift
expected_commit=313077708ea105cc79bf0a997338e14dae916f8c

if [[ ! -x "$source_root/.venv/bin/python" ]]; then
    echo "missing $source_root/.venv/bin/python; first run uv sync --locked --all-packages --all-groups --extra beam there" >&2
    exit 2
fi
if [[ $(git -C "$source_root" rev-parse HEAD) != "$expected_commit" ]]; then
    echo "source tree is not pinned Scroll commit $expected_commit" >&2
    exit 2
fi

cd "$source_root"
OPENAI_API_KEY=unused-upstream-test-stub .venv/bin/python -m pytest evaluation/tests -q "$@"
