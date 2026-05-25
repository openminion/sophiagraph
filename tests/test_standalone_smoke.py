from __future__ import annotations

import json
import subprocess
import sys
import tomllib


def test_python_m_sophiagraph_smoke(tmp_path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sophiagraph",
            "--root",
            str(tmp_path),
            "--seed",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["record_count"] == 1
    assert payload["db_path"].endswith("sophiagraph.sqlite3")


def test_console_script_contract_and_release_smoke_shape() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text())
    release_check = (root / "scripts" / "release_check.py").read_text()

    assert pyproject["project"]["scripts"]["sophiagraph-smoke"] == (
        "sophiagraph.__main__:main"
    )
    assert "twine" in release_check
    assert "sophiagraph-smoke" in release_check
    assert "VaultFilePayload" in release_check
    assert "retrieval_path_evidence" in release_check
