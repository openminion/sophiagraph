"""Local UI workbench artifact export example."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

from sophiagraph.ui import UiPreviewRequest, write_ui_preview


def run_example(root: str | Path) -> dict[str, object]:
    root = Path(root)
    result = write_ui_preview(
        UiPreviewRequest(
            screen="views",
            output_path=str(root / "sophiagraph-ui.html"),
            artifact_path=str(root / "sophiagraph-artifact.json"),
            embed_path=str(root / "sophiagraph-embed.html"),
            report_path=str(root / "sophiagraph-report.json"),
            markdown_report_path=str(root / "sophiagraph-report.md"),
        )
    )
    return {
        "screen": result.screen,
        "record_count": result.record_count,
        "node_count": result.node_count,
        "edge_count": result.edge_count,
        "artifact_written": (root / "sophiagraph-artifact.json").exists(),
        "report_written": (root / "sophiagraph-report.json").exists(),
    }


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="sophiagraph-ui-example-"))
    print(json.dumps(run_example(root), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
