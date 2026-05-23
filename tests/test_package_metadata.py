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
    assert (root / "scripts" / "release_check.py").is_file()


def test_package_readme_mentions_policy_and_quickstart() -> None:
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    assert "API_COMPATIBILITY.md" in readme
    assert "External Consumer Quickstart" in readme
    assert "create_memory_store()" in readme
