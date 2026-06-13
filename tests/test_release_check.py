from __future__ import annotations

from pathlib import Path


def test_release_check_covers_package_local_contracts() -> None:
    release_check = (
        Path(__file__).resolve().parents[1] / "scripts" / "release_check.py"
    ).read_text()

    assert "_assert_package_docs_shape" in release_check
    assert '"certification-readiness-matrix.md"' in release_check
    assert '"standalone-claim-alignment.md"' in release_check
    assert '"retrieval-boundary.md"' in release_check
    assert '"vector-conformance.md"' in release_check
    assert '"ui-contracts.md"' in release_check
    assert '"README.md"' in release_check
    assert "sophiagraph.ui" in release_check
    assert "plan_human_vault_import" in release_check
    assert "decide_replay" in release_check
