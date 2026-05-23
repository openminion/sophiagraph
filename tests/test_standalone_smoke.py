from __future__ import annotations

import json
import subprocess
import sys


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
