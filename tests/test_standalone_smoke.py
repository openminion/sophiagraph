from __future__ import annotations

import json
import subprocess
import sys
from threading import Thread
import tomllib
from urllib.request import urlopen

import pytest


def test_python_m_sophiagraph_smoke(tmp_path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sophiagraph",
            "--root",
            str(tmp_path),
            "--seed",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["record_count"] == 1
    assert payload["db_path"].endswith("sophiagraph.sqlite3")


def test_python_m_sophiagraph_ui_preview_writes_html(tmp_path) -> None:
    output_path = tmp_path / "preview.html"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sophiagraph",
            "ui-preview",
            "--screen",
            "views",
            "--html-out",
            str(output_path),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    html = output_path.read_text(encoding="utf-8")

    assert payload["screen"] == "views"
    assert payload["output_path"] == str(output_path.resolve())
    assert payload["record_count"] == 2
    assert "GraphFakos" in html
    assert "Provider Status" in html
    assert "Sophiagraph Durable Memory" in html
    assert "OpenMinion Integration" in html
    assert "Second-brain durable memory graph." in html
    assert "Auth Decision" in html


def test_sophiagraph_ui_preview_server_serves_visual_routes() -> None:
    from sophiagraph.ui.preview import UiPreviewRequest, make_ui_preview_server

    try:
        server = make_ui_preview_server(UiPreviewRequest(screen="views"), port=0)
    except PermissionError:
        pytest.skip("local socket binding is unavailable in this sandbox")
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(server.preview_url, timeout=5) as response:
            views_html = response.read().decode("utf-8")
        graph_url = server.preview_url.replace("/views", "/graph")
        with urlopen(graph_url, timeout=5) as response:
            graph_html = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert "Provider Status" in views_html
    assert "OpenMinion Integration" in views_html
    assert "href='/graph'" in views_html
    assert "Neighborhood" in graph_html


def test_console_script_contract_and_release_smoke_shape() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text())
    release_check = (root / "scripts" / "release_check.py").read_text()

    assert pyproject["project"]["scripts"]["sophiagraph-smoke"] == (
        "sophiagraph.__main__:main"
    )
    assert pyproject["project"]["scripts"]["sophiagraph-ui"] == (
        "sophiagraph.__main__:ui_preview_main"
    )
    assert "twine" in release_check
    assert "sophiagraph-smoke" in release_check
    assert "sophiagraph-ui" in release_check
    assert "VaultFilePayload" in release_check
    assert "retrieval_path_evidence" in release_check
