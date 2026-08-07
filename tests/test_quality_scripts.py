from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts import validate_quality_patterns

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


def test_quality_pattern_validator_includes_untracked_python_files(monkeypatch) -> None:
    observed_command: list[str] = []

    def fake_run(command, **_kwargs):
        observed_command.extend(command)
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout=b"src/sophiagraph/tracked.py\0tests/untracked.py\0",
        )

    monkeypatch.setattr(validate_quality_patterns.subprocess, "run", fake_run)

    files = validate_quality_patterns._git_python_files()

    assert files == [
        REPO_ROOT / "src/sophiagraph/tracked.py",
        REPO_ROOT / "tests/untracked.py",
    ]
    assert "--cached" in observed_command
    assert "--others" in observed_command
    assert "--exclude-standard" in observed_command
