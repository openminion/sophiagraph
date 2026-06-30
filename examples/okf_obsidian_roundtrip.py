"""OKF import/export example with optional Obsidian-compatible output."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from textwrap import dedent

from sophiagraph import MemoryNamespace, export_okf_bundle, import_okf_bundle


def _write_bundle(root: Path) -> None:
    (root / "references").mkdir(parents=True, exist_ok=True)
    (root / "index.md").write_text(
        dedent(
            """\
            ---
            title: Index
            ---
            # Index

            - [Roadmap](/Roadmap.md)
            """
        ),
        encoding="utf-8",
    )
    (root / "log.md").write_text(
        "---\ntitle: Log\n---\n# Log\n\n- Created example bundle.\n",
        encoding="utf-8",
    )
    (root / "Roadmap.md").write_text(
        dedent(
            """\
            ---
            type: concept
            title: Roadmap
            description: Example roadmap
            resource: https://example.com/roadmap
            tags: [example]
            timestamp: 2026-06-30T00:00:00+00:00
            aliases: [Plan]
            okf_version: 0.1-draft
            ---
            # Roadmap

            See [[Decision Log|decisions]].
            """
        ),
        encoding="utf-8",
    )
    (root / "Decision Log.md").write_text(
        "---\ntype: decision\ntitle: Decision Log\n---\n# Decision Log\n",
        encoding="utf-8",
    )


def run_example(root: str | Path) -> dict[str, object]:
    root = Path(root)
    bundle_root = root / "okf"
    bundle_root.mkdir(parents=True, exist_ok=True)
    _write_bundle(bundle_root)

    bundle = import_okf_bundle(
        bundle_root,
        namespace=MemoryNamespace(agent_id="example", graph_id="main"),
    )
    portable = export_okf_bundle(bundle)
    obsidian = export_okf_bundle(bundle, obsidian_compatible=True)

    return {
        "concept_count": bundle.manifest.concept_count,
        "index_count": bundle.manifest.index_count,
        "portable_paths": sorted(item.path for item in portable),
        "obsidian_contains_wikilink": any(
            "[[Decision Log.md|decisions]]" in item.content for item in obsidian
        ),
    }


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="sophiagraph-okf-example-"))
    print(json.dumps(run_example(root), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
