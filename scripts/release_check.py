#!/usr/bin/env python3
"""Deterministic release checks for the standalone sophiagraph package."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _run(cmd: list[str], *, cwd: Path, extra_env: dict[str, str] | None = None) -> None:
    print("+", " ".join(cmd))
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    subprocess.run(cmd, cwd=cwd, check=True, env=env)


def _assert_package_docs_shape(root: Path) -> None:
    required_paths = [
        root / "docs" / "README.md",
        root / "docs" / "reference" / "certification-readiness-matrix.md",
        root / "docs" / "reference" / "standalone-claim-alignment.md",
        root / "docs" / "reference" / "retrieval-boundary.md",
        root / "docs" / "reference" / "vector-conformance.md",
        root / "docs" / "reference" / "workspace-mode.md",
        root / "docs" / "reference" / "ui-contracts.md",
        root / "src" / "sophiagraph" / "README.md",
    ]
    missing = [
        str(path.relative_to(root)) for path in required_paths if not path.exists()
    ]
    if missing:
        raise RuntimeError(f"package docs/layout drifted: missing {missing!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run sophiagraph release checks")
    parser.add_argument(
        "--skip-twine", action="store_true", help="skip `twine check dist/*`"
    )
    parser.add_argument(
        "--skip-wheel-smoke", action="store_true", help="skip fresh-wheel install smoke"
    )
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    _assert_package_docs_shape(root)
    shutil.rmtree(root / "build", ignore_errors=True)
    shutil.rmtree(root / "dist", ignore_errors=True)
    for egg_info in root.glob("src/*.egg-info"):
        shutil.rmtree(egg_info, ignore_errors=True)

    python = sys.executable
    _run(
        [python, "-m", "pytest", "-q"],
        cwd=root,
        extra_env={"PYTHONPATH": str(root / "src")},
    )
    _run([python, "-m", "build"], cwd=root)
    if not args.skip_twine:
        dist_files = sorted((root / "dist").glob("*"))
        with tempfile.TemporaryDirectory(prefix="sophiagraph-twine-") as twine_tmp:
            twine_venv = Path(twine_tmp) / "venv"
            _run([python, "-m", "venv", str(twine_venv)], cwd=root)
            twine_python = twine_venv / "bin" / "python"
            twine_pip = twine_venv / "bin" / "pip"
            _run([str(twine_pip), "install", "twine>=5,<7"], cwd=root)
            _run(
                [
                    str(twine_python),
                    "-m",
                    "twine",
                    "check",
                    *[str(path) for path in dist_files],
                ],
                cwd=root,
            )
    if not args.skip_wheel_smoke:
        with tempfile.TemporaryDirectory(prefix="sophiagraph-release-") as tmpdir:
            tmp = Path(tmpdir)
            venv_dir = tmp / "venv"
            smoke_root = tmp / "smoke-root"
            _run([python, "-m", "venv", str(venv_dir)], cwd=root)
            pip = venv_dir / "bin" / "pip"
            wheel_python = venv_dir / "bin" / "python"
            smoke = venv_dir / "bin" / "sophiagraph-smoke"
            wheel = sorted((root / "dist").glob("sophiagraph-*.whl"))[-1]
            _run([str(pip), "install", str(wheel)], cwd=root)
            _run(
                [
                    str(wheel_python),
                    "-c",
                    (
                        "from sophiagraph import VaultFilePayload, all_simple_paths, "
                        "EmbeddingListOptions, FreshnessLedgerEntry, "
                        "HumanNoteInput, KuzuGraphBackendAdapter, MemoryEmbedding, "
                        "WorkspaceFilePrimaryNoteOptions, WorkspaceMetadata, "
                        "create_human_note, decide_replay, "
                        "import_vault_files, initialize_workspace, "
                        "plan_human_vault_import, plan_workspace_import, "
                        "scan_workspace_sync, workspace_sync_status, "
                        "retrieval_path_evidence; "
                        "from sophiagraph.ui import build_ui_screen_manifest"
                    ),
                ],
                cwd=root,
            )
            _run([str(smoke), "--root", str(smoke_root), "--seed", "--json"], cwd=root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
