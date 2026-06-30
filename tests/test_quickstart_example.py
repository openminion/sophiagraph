from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _example_pythonpath(root: Path) -> str:
    paths = [root / "src"]
    for candidate in (root / "graphfakos" / "src", root.parent / "graphfakos" / "src"):
        if candidate.exists():
            paths.append(candidate)
            break
    return os.pathsep.join(str(path) for path in paths)


def test_basic_usage_example_runs() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "examples" / "basic_usage.py")],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": _example_pythonpath(root)},
    )
    payload = json.loads(result.stdout)
    assert payload["listed_count"] == 1
    assert payload["searched_count"] == 1
    assert payload["imported_count"] == 1
