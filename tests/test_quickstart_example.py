from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_basic_usage_example_runs() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "examples" / "basic_usage.py")],
        check=True,
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(root / "src")},
    )
    payload = json.loads(result.stdout)
    assert payload["listed_count"] == 1
    assert payload["searched_count"] == 1
    assert payload["imported_count"] == 1
