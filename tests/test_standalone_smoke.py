from __future__ import annotations

import json
import subprocess
import sys
from threading import Thread
import tomllib
from urllib.request import urlopen

import pytest

import sophiagraph
import sophiagraph.__main__ as sophiagraph_cli
from sophiagraph.compatibility import DependencyCompatibility


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


def test_python_m_sophiagraph_reports_version_and_install_health() -> None:
    version = subprocess.run(
        [sys.executable, "-m", "sophiagraph", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    doctor = subprocess.run(
        [sys.executable, "-m", "sophiagraph", "doctor", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(doctor.stdout)

    assert version.stdout.strip() == sophiagraph.__version__
    assert payload["status"] == "ok"
    assert payload["package"] == {
        "name": "sophiagraph",
        "version": sophiagraph.__version__,
    }
    assert payload["python"]["supported"] is True
    assert payload["graphfakos"]["supported"] is True
    assert set(payload["optional_extras"]) == {
        "encryption",
        "kuzu",
        "neo4j",
        "qdrant",
        "telemetry",
    }


def test_bare_cli_shows_help_without_creating_runtime_state(tmp_path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "sophiagraph"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "commands:" in result.stdout
    assert "doctor" in result.stdout
    assert "workspace-init" in result.stdout
    assert not (tmp_path / ".sophiagraph-runtime").exists()


def test_explicit_smoke_subcommand_seeds_store(tmp_path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sophiagraph",
            "smoke",
            "--root",
            str(tmp_path),
            "--seed",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout)["record_count"] == 1


def test_unknown_command_fails_without_creating_runtime_state(tmp_path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "sophiagraph", "unknown-command"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "unknown command: unknown-command" in result.stderr
    assert "commands:" in result.stderr
    assert not (tmp_path / ".sophiagraph-runtime").exists()


def test_doctor_returns_failure_for_unsupported_required_dependency(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sophiagraph_cli,
        "graphfakos_compatibility",
        lambda: DependencyCompatibility(
            package="graphfakos",
            installed_version="0.0.5",
            supported=False,
            required_range=">=0.0.8,<1",
        ),
    )

    assert sophiagraph_cli.main(["doctor", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "error"


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
        "sophiagraph.__main__:smoke_main"
    )
    assert pyproject["project"]["scripts"]["sophiagraph"] == (
        "sophiagraph.__main__:main"
    )
    assert pyproject["project"]["scripts"]["sophiagraph-ui"] == (
        "sophiagraph.__main__:ui_preview_main"
    )
    assert pyproject["project"]["scripts"]["sophiagraph-server"] == (
        "sophiagraph.server.__main__:main"
    )
    assert "twine" in release_check
    assert '"--help"' in release_check
    assert '"doctor"' in release_check
    assert '"smoke"' in release_check
    assert "sophiagraph-smoke" in release_check
    assert "sophiagraph-ui" in release_check
    assert "sophiagraph-server" in release_check
    assert "sophiagraph-artifact.json" in release_check
    assert "sophiagraph-report.json" in release_check
    assert "sophiagraph-report.md" in release_check
    assert "graphfakos-ui" in release_check
    assert "VaultFilePayload" in release_check
    assert "retrieval_path_evidence" in release_check
