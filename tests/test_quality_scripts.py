from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_quality_pattern_validator_passes_current_baselines() -> None:
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "validate_quality_patterns.py"),
            "--check",
            "all",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
