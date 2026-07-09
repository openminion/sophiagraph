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
    artifact_path = tmp_path / "sophiagraph-artifact.json"
    embed_path = tmp_path / "sophiagraph-embed.html"
    report_path = tmp_path / "sophiagraph-report.json"
    markdown_path = tmp_path / "sophiagraph-report.md"
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
            "--artifact-out",
            str(artifact_path),
            "--embed-out",
            str(embed_path),
            "--report-out",
            str(report_path),
            "--markdown-report-out",
            str(markdown_path),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    html = output_path.read_text(encoding="utf-8")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert payload["screen"] == "provider_status"
    assert payload["output_path"] == str(output_path.resolve())
    assert payload["record_count"] == 2
    assert payload["artifact"]["artifact"] is True
    assert payload["embed"]["embedded"] is True
    assert payload["report"]["report"] is True
    assert payload["markdown_report"]["markdown_report"] is True
    assert "GraphFakos" in html
    assert "Provider Status" in html
    assert "Sophiagraph Durable Memory" in html
    assert "Integration Commands" in html
    assert "Second-brain durable memory graph." in html
    assert "sophiagraph-ui --workspace" in html
    assert "Auth Decision" in html
    assert "data-graphfakos-embed='true'" in embed_path.read_text(encoding="utf-8")
    assert report["graph"]["provider_label"] == "Sophiagraph"
    assert artifact["provider_id"] == "sophiagraph"
    assert "# GraphFakos Report" in markdown_path.read_text(encoding="utf-8")


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
    assert "Integration Commands" in views_html
    assert "href='/graph" in views_html
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
    assert pyproject["project"]["scripts"]["sophiagraph-server"] == (
        "sophiagraph.server.__main__:main"
    )
    assert "twine" in release_check
    assert "sophiagraph-smoke" in release_check
    assert "sophiagraph-ui" in release_check
    assert "sophiagraph-server" in release_check
    assert "sophiagraph-artifact.json" in release_check
    assert "sophiagraph-report.json" in release_check
    assert "sophiagraph-report.md" in release_check
    assert "graphfakos-ui" in release_check
    assert "VaultFilePayload" in release_check
    assert "retrieval_path_evidence" in release_check
