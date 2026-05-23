from __future__ import annotations

from pathlib import Path


def test_sophiagraph_package_imports() -> None:
    import sophiagraph
    import sophiagraph.audit
    import sophiagraph.contracts
    import sophiagraph.models
    import sophiagraph.portability
    import sophiagraph.query
    import sophiagraph.storage
    import sophiagraph.temporal
    import sophiagraph.trust

    assert sophiagraph.__version__ == "0.1.0"
    assert callable(sophiagraph.create_sqlite_store)
    assert sophiagraph.DEFAULT_DB_FILENAME == "sophiagraph.sqlite3"
    assert sophiagraph.MemoryNamespace(agent_id="codex").agent_id == "codex"
    assert sophiagraph.MemoryRecord.__name__ == "MemoryRecord"
    assert sophiagraph.ListQueryOptions.__name__ == "ListQueryOptions"


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
