"""Live workspace sync example using package-local public APIs."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

from sophiagraph import (
    MemoryNamespace,
    apply_workspace_sync,
    initialize_workspace,
    scan_workspace_sync,
    workspace_sync_status,
)


def run_example(root: str | Path) -> dict[str, object]:
    root = Path(root)
    workspace = root / "workspace"
    notes = root / "notes"
    note_path = notes / "notes" / "hello.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text("# Hello\n\nThis note is file-primary.\n", encoding="utf-8")

    namespace = MemoryNamespace(agent_id="example", graph_id="main")
    initialize_workspace(
        workspace,
        scope="agent:example",
        namespace=namespace,
        label="example-workspace",
        vault_id="example-vault",
    )
    plan = scan_workspace_sync(workspace, notes)
    applied = apply_workspace_sync(workspace, notes, plan=plan)
    status = workspace_sync_status(workspace, notes)

    return {
        "created_count": plan.created_count,
        "imported_paths": list(applied.imported_paths),
        "fresh_count": status.fresh_count,
        "tracked_count": status.tracked_count,
    }


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="sophiagraph-workspace-example-"))
    print(json.dumps(run_example(root), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
