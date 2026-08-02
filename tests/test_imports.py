from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import tomllib


def test_sophiagraph_package_imports() -> None:
    import sophiagraph
    import sophiagraph.audit
    import sophiagraph.contracts
    import sophiagraph.human
    import sophiagraph.models
    import sophiagraph.okf
    import sophiagraph.portability
    import sophiagraph.query
    import sophiagraph.storage
    import sophiagraph.temporal
    import sophiagraph.trust
    import sophiagraph.ui
    import sophiagraph.workspace

    assert sophiagraph.__version__ == "0.0.6rc1"
    assert callable(sophiagraph.create_sqlite_store)
    assert sophiagraph.DEFAULT_DB_FILENAME == "sophiagraph.sqlite3"
    assert sophiagraph.MemoryNamespace(agent_id="codex").agent_id == "codex"
    assert sophiagraph.MemoryRecord.__name__ == "MemoryRecord"
    assert sophiagraph.ListQueryOptions.__name__ == "ListQueryOptions"
    assert sophiagraph.human.HumanWorkspaceSnapshot.__name__ == "HumanWorkspaceSnapshot"
    assert sophiagraph.ui.UiTransportBoundary.__name__ == "UiTransportBoundary"
    assert sophiagraph.workspace.WorkspaceMetadata.__name__ == "WorkspaceMetadata"
    assert sophiagraph.okf.OkfBundleManifest.__name__ == "OkfBundleManifest"


def test_top_level_public_api_and_version_metadata_are_stable() -> None:
    import sophiagraph

    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text())
    expected_exports = {
        "EntitySummary",
        "MemoryRecord",
        "MemoryNamespace",
        "SophiaGraphMemoryStore",
        "SophiaGraphSqliteStore",
        "HumanWorkspaceSnapshot",
        "SummaryContextRequest",
        "WorkspaceMetadata",
        "OkfBundleManifest",
        "VaultFilePayload",
        "all_simple_paths",
        "assemble_entity_summary_context",
        "retrieval_path_evidence",
        "create_sqlite_store",
        "import_okf_bundle",
        "initialize_workspace",
    }

    assert sophiagraph.__version__ == pyproject["project"]["version"]
    assert expected_exports <= set(sophiagraph.__all__)
    assert all(
        not (name.startswith("_") and not name.endswith("__"))
        for name in sophiagraph.__all__
    )


def test_models_public_all_excludes_private_cast_helpers() -> None:
    import sophiagraph.models as models

    assert "MemoryRecord" in models.__all__
    assert "MemoryCandidate" in models.__all__
    assert "_as_memory_type" not in models.__all__
    assert callable(models._as_memory_type)


def test_sophiagraph_package_does_not_import_openminion_from_source() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "sophiagraph"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text()
        if "import openminion" in text or "from openminion" in text:
            offenders.append(str(path))
    assert offenders == []


def test_sophiagraph_core_source_does_not_import_server_subpackage() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "sophiagraph"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if "/server/" in path.as_posix():
            continue
        text = path.read_text()
        if "import sophiagraph.server" in text or "from sophiagraph.server" in text:
            offenders.append(str(path))
    assert offenders == []


def test_sophiagraph_import_does_not_load_server_subpackage() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sophiagraph, sys; print('sophiagraph.server' in sys.modules)",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "False"
