from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


EXAMPLE_EXPECTATIONS = {
    "basic_usage.py": {"listed_count": 1, "searched_count": 1, "imported_count": 1},
    "workspace_sync_demo.py": {"created_count": 1, "fresh_count": 1},
    "okf_obsidian_roundtrip.py": {
        "concept_count": 2,
        "index_count": 1,
        "obsidian_contains_wikilink": True,
    },
    "graph_backend_export.py": {
        "backend": "fake",
        "node_count": 2,
        "edge_count": 1,
        "path": ["rec-a", "rec-b"],
    },
    "privacy_redaction.py": {
        "exported_record_ids": ["rec-public", "rec-private"],
        "redacted_record_ids": ["rec-private"],
        "omitted_record_ids": [],
    },
    "benchmark_conformance.py": {
        "suite_id": "sophiagraph-public-conformance",
        "passed": True,
        "failed": 0,
    },
    "ui_workbench_export.py": {
        "artifact_written": True,
        "report_written": True,
    },
}


@pytest.mark.parametrize("example_name", sorted(EXAMPLE_EXPECTATIONS))
def test_public_example_runs(example_name: str) -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "examples" / example_name)],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
    )
    payload = json.loads(result.stdout)
    for key, value in EXAMPLE_EXPECTATIONS[example_name].items():
        assert payload[key] == value
