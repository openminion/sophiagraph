from __future__ import annotations

from pathlib import Path


def test_package_release_artifacts_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "LICENSE").is_file()
    assert (root / "RELEASING.md").is_file()
    assert (root / "pyproject.toml").is_file()


def test_package_readme_mentions_release_runbook() -> None:
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    assert "RELEASING.md" in readme
    assert "Apache-2.0" in readme


def test_package_policy_and_release_automation_docs_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "API_COMPATIBILITY.md").is_file()
    assert (root / "docs" / "README.md").is_file()
    assert (root / "docs" / "certification-readiness-matrix.md").is_file()
    assert (root / "docs" / "standalone-claim-alignment.md").is_file()
    assert (root / "docs" / "retrieval-boundary.md").is_file()
    assert (root / "docs" / "vector-conformance.md").is_file()
    assert (root / "docs" / "workspace-mode.md").is_file()
    assert (root / "docs" / "ui-contracts.md").is_file()
    assert (root / "src" / "sophiagraph" / "README.md").is_file()
    assert (root / "scripts" / "release_check.py").is_file()


def test_package_readme_mentions_policy_and_quickstart() -> None:
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    assert "API_COMPATIBILITY.md" in readme
    assert "External Consumer Quickstart" in readme
    assert "create_memory_store()" in readme
    assert "docs/standalone-claim-alignment.md" in readme
    assert "docs/retrieval-boundary.md" in readme
    assert "docs/workspace-mode.md" in readme


def test_package_metadata_exposes_canonical_public_urls() -> None:
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()

    assert "https://github.com/openminion/sophiagraph" in pyproject
    assert "https://pypi.org/project/sophiagraph/" in pyproject
    assert "https://github.com/openminion/sophiagraph" in readme
    assert "https://pypi.org/project/sophiagraph" in readme
