from __future__ import annotations

from pathlib import Path


def test_storage_operations_files_do_not_contain_forbidden_tokens() -> None:
    forbidden = {
        "openai",
        "anthropic",
        "Claude",
        "llm_complete",
        "auto_restore",
        "summarize_backup",
        "infer_corruption",
        "generate_snapshot_name",
    }
    root = Path(__file__).resolve().parents[1] / "src" / "sophiagraph"
    targets = [
        root / "storage" / "operations.py",
        root / "models" / "storage_operations.py",
    ]
    for path in targets:
        source = path.read_text(encoding="utf-8")
        hits = {token for token in forbidden if token in source}
        assert not hits, f"{path.name} contains forbidden tokens: {sorted(hits)}"
