from __future__ import annotations

from pathlib import Path


def test_root_layout_stays_clean_and_intentional() -> None:
    root = Path(__file__).resolve().parents[1]

    assert (root / "docs" / "README.md").is_file()
    assert (root / "docs" / "reference").is_dir()
    assert (root / "src" / "sophiagraph" / "README.md").is_file()

    assert not (root / "fixtures").exists()
    assert not (root / "handoff").exists()


def test_docs_reference_surface_contains_expected_package_refs() -> None:
    root = Path(__file__).resolve().parents[1] / "docs" / "reference"

    expected = {
        "certification-readiness-matrix.md",
        "ui-contracts.md",
        "vector-conformance.md",
    }

    assert expected.issubset({path.name for path in root.iterdir() if path.is_file()})
