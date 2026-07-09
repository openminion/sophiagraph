from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def test_cli_help_lists_serve_stdio_subcommand() -> None:
    root = Path(__file__).resolve().parents[1]
    env = {"PYTHONPATH": str(root / "src")}
    help_run = subprocess.run(
        [sys.executable, "-m", "sophiagraph.server", "--help"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "serve-stdio" in help_run.stdout


def test_serve_stdio_help_documents_backend_option_and_kmsr_02_blocker() -> None:
    root = Path(__file__).resolve().parents[1]
    env = {"PYTHONPATH": str(root / "src")}
    help_run = subprocess.run(
        [sys.executable, "-m", "sophiagraph.server", "serve-stdio", "--help"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "--backend" in help_run.stdout
    assert "KMSR-02" in help_run.stdout
