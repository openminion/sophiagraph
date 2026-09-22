from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import validate_quality_patterns

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_quality_pattern_validator_passes_current_baselines() -> None:
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "validate_quality_patterns.py"),
            "--check",
            "all",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_quality_pattern_validator_includes_untracked_python_files(monkeypatch) -> None:
    observed_command: list[str] = []

    def fake_run(command, **_kwargs):
        observed_command.extend(command)
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout=b"src/sophiagraph/tracked.py\0tests/untracked.py\0",
        )

    monkeypatch.setattr(validate_quality_patterns.subprocess, "run", fake_run)

    files = validate_quality_patterns._git_python_files()

    assert files == [
        REPO_ROOT / "src/sophiagraph/tracked.py",
        REPO_ROOT / "tests/untracked.py",
    ]
    assert "--cached" in observed_command
    assert "--others" in observed_command
    assert "--exclude-standard" in observed_command


BASELINES = (
    (
        "MAX_FILE_LOC_BASELINE",
        "_max_file_loc_rows",
        ("src/a.py", 1200, "reviewed reason"),
    ),
    (
        "METHOD_LOC_BASELINE",
        "_method_loc_rows",
        ("src/a.py", "work", 120, "reviewed reason"),
    ),
    (
        "HELPER_DUPLICATES_BASELINE",
        "_helper_duplicate_rows",
        ("src", "_work", "src/a.py,src/b.py", "reviewed reason"),
    ),
    ("FILENAME_UNDERSCORE_BASELINE", "_filename_underscore_rows", ("src/a_b_c.py", 2)),
    (
        "BROAD_EXCEPTION_BASELINE",
        "_broad_exception_rows",
        ("src/a.py", 2, 1, "reviewed reason"),
    ),
    (
        "PATH_STRUCTURE_BASELINE",
        "_path_structure_rows",
        ("a_helpers.py", "redundant suffix"),
    ),
)


def _baseline_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for constant, row_function, row in BASELINES:
        path = tmp_path / f"{constant}.tsv"
        path.write_text(
            "# baseline\n" + "\t".join(map(str, row)) + "\n", encoding="utf-8"
        )
        monkeypatch.setattr(validate_quality_patterns, constant, path)
        monkeypatch.setattr(
            validate_quality_patterns, row_function, lambda _project, row=row: [row]
        )
        paths[constant] = path
    return paths


@pytest.mark.parametrize(
    ("row_function", "updated_row"),
    [
        ("_max_file_loc_rows", ("src/a.py", 1201, "new default")),
        ("_method_loc_rows", ("src/a.py", "work", 121, "new default")),
        (
            "_helper_duplicate_rows",
            ("src", "_work", "src/a.py,src/b.py,src/c.py", "new default"),
        ),
        (
            "_helper_duplicate_rows",
            ("src", "_work", "src/a.py,src/c.py", "new default"),
        ),
        ("_filename_underscore_rows", ("src/a_b_c.py", 3)),
        ("_broad_exception_rows", ("src/a.py", 2, 2, "new default")),
        ("_broad_exception_rows", ("src/a.py", 3, 1, "new default")),
        ("_path_structure_rows", ("a_helpers.py", "new violation")),
    ],
)
def test_baseline_writer_rejects_new_debt_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    row_function: str,
    updated_row: tuple[object, ...],
) -> None:
    paths = _baseline_fixture(tmp_path, monkeypatch)
    original = {name: path.read_bytes() for name, path in paths.items()}
    monkeypatch.setattr(
        validate_quality_patterns, row_function, lambda _project: [updated_row]
    )

    with pytest.raises(SystemExit):
        validate_quality_patterns.write_baselines(
            validate_quality_patterns._project_info()
        )

    assert {name: path.read_bytes() for name, path in paths.items()} == original


@pytest.mark.parametrize(
    ("row_function", "new_row"),
    [
        ("_max_file_loc_rows", ("src/new.py", 1200, "new default")),
        ("_method_loc_rows", ("src/a.py", "new_work", 120, "new default")),
        (
            "_helper_duplicate_rows",
            ("src", "_new_work", "src/a.py,src/b.py", "new default"),
        ),
        ("_filename_underscore_rows", ("src/new_a_b.py", 2)),
        ("_broad_exception_rows", ("src/new.py", 1, 0, "new default")),
        ("_path_structure_rows", ("new_helpers.py", "redundant suffix")),
    ],
)
def test_baseline_writer_rejects_new_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    row_function: str,
    new_row: tuple[object, ...],
) -> None:
    paths = _baseline_fixture(tmp_path, monkeypatch)
    original = {name: path.read_bytes() for name, path in paths.items()}
    old_row = next(row for _, name, row in BASELINES if name == row_function)
    monkeypatch.setattr(
        validate_quality_patterns, row_function, lambda _project: [old_row, new_row]
    )

    with pytest.raises(SystemExit):
        validate_quality_patterns.write_baselines(
            validate_quality_patterns._project_info()
        )

    assert {name: path.read_bytes() for name, path in paths.items()} == original


def test_baseline_writer_accepts_reductions_and_removals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _baseline_fixture(tmp_path, monkeypatch)
    paths["HELPER_DUPLICATES_BASELINE"].write_text(
        "# baseline\nsrc\t_work\tsrc/a.py,src/b.py,src/c.py\treviewed reason\n"
    )
    paths["FILENAME_UNDERSCORE_BASELINE"].write_text("# baseline\nsrc/a_b_c.py\t3\n")
    monkeypatch.setattr(
        validate_quality_patterns,
        "_max_file_loc_rows",
        lambda _project: [("src/a.py", 1100, "new default")],
    )
    monkeypatch.setattr(
        validate_quality_patterns,
        "_method_loc_rows",
        lambda _project: [("src/a.py", "work", 110, "new default")],
    )
    monkeypatch.setattr(
        validate_quality_patterns,
        "_helper_duplicate_rows",
        lambda _project: [("src", "_work", "src/a.py,src/b.py", "new default")],
    )
    monkeypatch.setattr(
        validate_quality_patterns,
        "_filename_underscore_rows",
        lambda _project: [("src/a_b_c.py", 2)],
    )
    monkeypatch.setattr(
        validate_quality_patterns,
        "_broad_exception_rows",
        lambda _project: [("src/a.py", 1, 0, "new default")],
    )
    monkeypatch.setattr(
        validate_quality_patterns, "_path_structure_rows", lambda _project: []
    )

    validate_quality_patterns.write_baselines(validate_quality_patterns._project_info())

    assert (
        "src/a.py\t1100\treviewed reason" in paths["MAX_FILE_LOC_BASELINE"].read_text()
    )
    assert (
        "src/a.py\twork\t110\treviewed reason"
        in paths["METHOD_LOC_BASELINE"].read_text()
    )
    assert (
        "src\t_work\tsrc/a.py,src/b.py\treviewed reason"
        in paths["HELPER_DUPLICATES_BASELINE"].read_text()
    )
    assert "src/a_b_c.py\t2" in paths["FILENAME_UNDERSCORE_BASELINE"].read_text()
    assert (
        "src/a.py\t1\t0\treviewed reason"
        in paths["BROAD_EXCEPTION_BASELINE"].read_text()
    )
    assert "a_helpers.py" not in paths["PATH_STRUCTURE_BASELINE"].read_text()


def test_baseline_writer_accepts_equal_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _baseline_fixture(tmp_path, monkeypatch)
    original = {name: path.read_bytes() for name, path in paths.items()}

    validate_quality_patterns.write_baselines(validate_quality_patterns._project_info())

    assert {name: path.read_bytes() for name, path in paths.items()} == original


def test_baseline_writer_does_not_bootstrap_missing_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _baseline_fixture(tmp_path, monkeypatch)
    paths["METHOD_LOC_BASELINE"].unlink()
    original = {
        name: path.read_bytes() for name, path in paths.items() if path.exists()
    }

    with pytest.raises(SystemExit, match="missing baseline"):
        validate_quality_patterns.write_baselines(
            validate_quality_patterns._project_info()
        )

    assert {
        name: path.read_bytes() for name, path in paths.items() if path.exists()
    } == original


def test_baseline_writer_rejects_mixed_update_before_any_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _baseline_fixture(tmp_path, monkeypatch)
    original = {name: path.read_bytes() for name, path in paths.items()}
    monkeypatch.setattr(
        validate_quality_patterns,
        "_max_file_loc_rows",
        lambda _project: [("src/a.py", 1100, "new default")],
    )
    monkeypatch.setattr(
        validate_quality_patterns,
        "_path_structure_rows",
        lambda _project: [("new_helpers.py", "redundant suffix")],
    )

    with pytest.raises(SystemExit):
        validate_quality_patterns.write_baselines(
            validate_quality_patterns._project_info()
        )

    assert {name: path.read_bytes() for name, path in paths.items()} == original


def test_cli_cannot_admit_new_122_line_method(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(
        REPO_ROOT / "scripts" / "validate_quality_patterns.py", scripts / "quality.py"
    )
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "sophiagraph"\n')
    source = tmp_path / "src" / "sophiagraph"
    source.mkdir(parents=True)
    (source / "a.py").write_text("def too_long():\n" + "    pass\n" * 121)
    baselines = scripts / "baselines"
    baselines.mkdir()
    for constant, _, _ in BASELINES:
        path = getattr(validate_quality_patterns, constant)
        (baselines / path.name).write_text("# baseline\n", encoding="utf-8")
    original = {path.name: path.read_bytes() for path in baselines.iterdir()}

    result = subprocess.run(
        [sys.executable, str(scripts / "quality.py"), "--write-baselines"],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "method_loc_baseline.tsv: new debt" in result.stderr
    assert {path.name: path.read_bytes() for path in baselines.iterdir()} == original
