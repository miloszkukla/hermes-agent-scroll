"""Fixed, objective coding trajectories for the paired Scroll evaluation."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CodingTrajectory:
    identifier: str
    category: str
    scenario: str
    prompt: str
    history_seed: str

    def history(self) -> tuple[dict[str, str], ...]:
        entries = [
            {"role": "user", "content": f"Continue task {self.identifier}. Preserve APIs and use the focused test as the executable contract."},
            {"role": "assistant", "content": "I will inspect the workspace, run the focused test, then make the smallest repair."},
            {"role": "user", "content": "The prior terminal call failed because the test command used the wrong working directory. Retry from the task workspace."},
            {"role": "assistant", "content": "I will retry the tool call and keep the failure evidence in mind."},
        ]
        chunk = (f"build {self.identifier} {self.history_seed} " * 140).strip()
        for number in range(56):
            entries.append({"role": "user", "content": f"Build/test log chunk {number:02d}: {chunk}"})
            entries.append({"role": "assistant", "content": f"Recorded log chunk {number:02d}; no source change is complete yet."})
        return tuple(entries)


def _category(index: int) -> str:
    return ("labels", "flags", "limits", "routes", "render")[index % 5]


def _scenario(index: int) -> str:
    return "automatic-compaction" if index < 8 else "manual-compaction" if index < 14 else "cache-loss-resume"


TRAJECTORIES = tuple(CodingTrajectory(
    f"coding/{index + 1:02d}-{_category(index)}", _category(index), _scenario(index),
    "Use the terminal in the current workspace to repair the package so its focused test passes. Do not edit tests or change public API names. Run the focused test before reporting completion.",
    f"seed-{index + 1:02d}-{_category(index)}",
) for index in range(20))


def by_identifier(identifier: str) -> CodingTrajectory:
    for trajectory in TRAJECTORIES:
        if trajectory.identifier == identifier:
            return trajectory
    raise KeyError(identifier)


def _files(trajectory: CodingTrajectory) -> dict[str, str]:
    suffix = trajectory.identifier.split("-", 1)[0].rsplit("/", 1)[-1]
    if trajectory.category == "labels":
        return {
            "app/labels.py": "def render(value):\n    return '|'.join(part.lower() for part in value.split(','))\n",
            "tests/test_task.py": f"from app.labels import render\n\ndef test_render():\n    assert render(' Amber-{suffix}, Blue-{suffix} ') == 'amber-{suffix}|blue-{suffix}'\n",
        }
    if trajectory.category == "flags":
        return {
            "app/flags.py": "def enabled(value):\n    return value == 'yes'\n",
            "tests/test_task.py": "from app.flags import enabled\n\ndef test_enabled():\n    assert enabled(' YES ')\n",
        }
    if trajectory.category == "limits":
        return {
            "app/limits.py": "def is_full(count, limit):\n    return count > limit\n",
            "tests/test_task.py": "from app.limits import is_full\n\ndef test_is_full_at_limit():\n    assert is_full(10, 10)\n",
        }
    if trajectory.category == "routes":
        return {
            "app/routes.py": "def api_path(name):\n    return '/api/' + name\n",
            "app/client.py": "from .routes import api_path\n\ndef endpoint(name):\n    return api_path(name)\n",
            "tests/test_task.py": f"from app.client import endpoint\n\ndef test_endpoint():\n    assert endpoint(' amber-{suffix} ') == '/api/amber-{suffix}'\n",
        }
    return {
        "app/normalizer.py": "def normalize(value):\n    return value.lower()\n",
        "app/render.py": "from .normalizer import normalize\n\ndef render(value):\n    return 'label:' + normalize(value)\n",
        "tests/test_task.py": f"from app.render import render\n\ndef test_render():\n    assert render('amber-{suffix}') == 'LABEL:AMBER-{suffix}'\n",
    }


def write_workspace(trajectory: CodingTrajectory, workspace: Path) -> None:
    for relative, content in _files(trajectory).items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (workspace / "app" / "__init__.py").write_text("", encoding="utf-8")


def verify_workspace(workspace: Path) -> bool:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(workspace)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"], cwd=workspace, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0
