#!/usr/bin/env python3
"""Validate package-local quality ratchets.

The checks intentionally focus on structural hygiene that Ruff does not cover:
file/function size, duplicate private helpers, broad exceptions, path/name drift,
bare type ignores, and hidden imports from sibling package roots.
"""

from __future__ import annotations

import argparse
import ast
import collections
import re
import sys
import tokenize
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = REPO_ROOT / "scripts" / "baselines"
MAX_FILE_LOC_BASELINE = BASELINE_ROOT / "max_file_loc_baseline.tsv"
METHOD_LOC_BASELINE = BASELINE_ROOT / "method_loc_baseline.tsv"
HELPER_DUPLICATES_BASELINE = BASELINE_ROOT / "helper_duplicates_baseline.tsv"
FILENAME_UNDERSCORE_BASELINE = BASELINE_ROOT / "filename_underscore_hygiene.tsv"
BROAD_EXCEPTION_BASELINE = BASELINE_ROOT / "broad_exception_baseline.tsv"
PATH_STRUCTURE_BASELINE = BASELINE_ROOT / "path_structure_hygiene.tsv"

MAX_FILE_LOC_CEILING = 1000
METHOD_LOC_CEILING = 100
UNDERSCORE_THRESHOLD = 1
EXEMPT_FILENAMES = {"__init__.py", "__main__.py"}
INFO_ONLY_FILENAME_ROOTS = {"tests"}
KNOWN_PACKAGE_ROOTS = {
    "graphfakos",
    "openminion",
    "openminion_eval",
    "pragmagraph",
    "sophiagraph",
}
DEPRECATED_DIR_NAMES = {
    "handlers": "use a domain owner folder",
    "helpers": "use a concrete owner folder",
    "processors": "use a domain owner folder",
    "utils": "use a concrete owner folder",
}
REDUNDANT_SUFFIX_RULES = {
    "_helpers": "prefer an explicit owner name over *_helpers.py",
    "_manager": "prefer the managed domain name over *_manager.py",
    "_processor": "prefer the processed domain name over *_processor.py",
    "_support": "prefer an explicit owner name over *_support.py",
    "_utils": "prefer a concrete owner name over *_utils.py",
    "_wrapper": "prefer the boundary name over *_wrapper.py",
}
HELPER_NAME_ALLOWLIST = {
    "_as_bool",
    "_as_float",
    "_as_int",
    "_as_str",
    "_as_str_list",
    "_build",
    "_coerce_bool",
    "_coerce_float",
    "_coerce_int",
    "_coerce_str",
    "_count",
    "_debug",
    "_dedupe",
    "_format",
    "_from_dict",
    "_get",
    "_html_escape",
    "_json",
    "_normalize",
    "_parse",
    "_render",
    "_resolve",
    "_safe_json",
    "_to_dict",
    "_validate",
}
TYPE_IGNORE_RE = re.compile(r"#\s*type:\s*ignore(?:\[([^\]]+)\])?", re.IGNORECASE)


@dataclass(frozen=True)
class ProjectInfo:
    name: str
    import_root: str
    source_root: Path
    dependency_roots: frozenset[str]


def _project_info() -> ProjectInfo:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    project = pyproject.get("project", {})
    name = str(project.get("name", REPO_ROOT.name))
    import_root = name.replace("-", "_")
    dependencies = project.get("dependencies", [])
    dependency_roots = frozenset(_dependency_root(str(item)) for item in dependencies)
    return ProjectInfo(
        name=name,
        import_root=import_root,
        source_root=REPO_ROOT / "src" / import_root,
        dependency_roots=dependency_roots,
    )


def _dependency_root(dependency: str) -> str:
    name = re.split(r"[<>=!~;\[]", dependency, maxsplit=1)[0].strip()
    return name.replace("-", "_")


def _scan_roots(project: ProjectInfo) -> tuple[Path, ...]:
    roots = (
        project.source_root,
        REPO_ROOT / "scripts",
        REPO_ROOT / "tests",
        REPO_ROOT / "examples",
    )
    return tuple(root for root in roots if root.exists())


def _python_files(*roots: Path) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        files.extend(
            path
            for path in root.rglob("*.py")
            if path.is_file() and "__pycache__" not in path.parts
        )
    return sorted(files)


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _load_tsv(path: Path, width: int) -> set[tuple[str, ...]]:
    if not path.exists():
        return set()
    rows: set[tuple[str, ...]] = set()
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = tuple(part.strip() for part in line.split("\t"))
        if len(parts) != width:
            raise SystemExit(
                f"{path.relative_to(REPO_ROOT)} line {line_number}: "
                f"expected {width} tab-separated field(s)"
            )
        rows.add(parts)
    return rows


def _write_tsv(path: Path, header: str, rows: list[tuple[object, ...]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [header]
    lines.extend("\t".join(str(value) for value in row) for row in rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _compare_baseline(
    *,
    name: str,
    current: set[tuple[str, ...]],
    baseline: set[tuple[str, ...]],
    render: callable,
) -> list[str]:
    findings: list[str] = []
    for row in sorted(current - baseline):
        findings.append(f"new_{name}: {render(row)}")
    for row in sorted(baseline - current):
        findings.append(f"stale_{name}: {render(row)}")
    return findings


def _count_loc(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _max_file_loc_rows(project: ProjectInfo) -> list[tuple[str, int, str]]:
    rows: list[tuple[str, int, str]] = []
    for path in _python_files(project.source_root):
        loc = _count_loc(path)
        if loc > MAX_FILE_LOC_CEILING:
            rows.append((_rel(path), loc, "existing over-ceiling file ratchet"))
    return rows


def check_max_file_loc(project: ProjectInfo) -> list[str]:
    current = {
        (path, str(loc), reason) for path, loc, reason in _max_file_loc_rows(project)
    }
    baseline = _load_tsv(MAX_FILE_LOC_BASELINE, 3)
    indexed_baseline = {row[0]: row for row in baseline}
    findings: list[str] = []
    for path, loc, reason in sorted(current):
        baseline_row = indexed_baseline.get(path)
        if baseline_row is None:
            findings.append(f"new_over_ceiling_file: {path} has {loc} LOC")
            continue
        if int(loc) > int(baseline_row[1]):
            findings.append(
                f"baselined_file_grew: {path} has {loc} LOC > baseline {baseline_row[1]}"
            )
        if not reason:
            findings.append(f"missing_file_loc_reason: {path}")
    current_paths = {row[0] for row in current}
    for path in sorted(set(indexed_baseline) - current_paths):
        findings.append(f"stale_file_loc_baseline: {path}")
    return findings


def _node_loc(node: ast.AST) -> int:
    start = getattr(node, "lineno", 0)
    end = getattr(node, "end_lineno", 0)
    return (
        max(0, end - start + 1)
        if isinstance(start, int) and isinstance(end, int)
        else 0
    )


class _FunctionCollector(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.stack: list[str] = []
        self.rows: list[tuple[str, str, int, str]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record(node)
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record(node)
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def _record(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        loc = _node_loc(node)
        if loc <= METHOD_LOC_CEILING:
            return
        qualname = ".".join([*self.stack, node.name]) if self.stack else node.name
        self.rows.append(
            (self.path, qualname, loc, "existing over-ceiling function ratchet")
        )


def _method_loc_rows(project: ProjectInfo) -> list[tuple[str, str, int, str]]:
    rows: list[tuple[str, str, int, str]] = []
    for path in _python_files(project.source_root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        collector = _FunctionCollector(_rel(path))
        collector.visit(tree)
        rows.extend(collector.rows)
    return rows


def check_method_loc(project: ProjectInfo) -> list[str]:
    current = {
        (path, qualname, str(loc), reason)
        for path, qualname, loc, reason in _method_loc_rows(project)
    }
    baseline = _load_tsv(METHOD_LOC_BASELINE, 4)
    baseline_by_method = {(row[0], row[1]): row for row in baseline}
    findings: list[str] = []
    for path, qualname, loc, _reason in sorted(current):
        baseline_row = baseline_by_method.get((path, qualname))
        if baseline_row is None:
            findings.append(f"new_over_ceiling_method: {path}:{qualname} has {loc} LOC")
            continue
        if int(loc) > int(baseline_row[2]):
            findings.append(
                f"baselined_method_grew: {path}:{qualname} has {loc} LOC > baseline {baseline_row[2]}"
            )
    current_methods = {(row[0], row[1]) for row in current}
    for path, qualname in sorted(set(baseline_by_method) - current_methods):
        findings.append(f"stale_method_loc_baseline: {path}:{qualname}")
    return findings


def _private_functions(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return []
    names: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_") and node.name not in HELPER_NAME_ALLOWLIST:
                names.append(node.name)
    return names


def _helper_duplicate_rows(project: ProjectInfo) -> list[tuple[str, str, str, str]]:
    by_directory: dict[Path, dict[str, list[Path]]] = collections.defaultdict(
        lambda: collections.defaultdict(list)
    )
    for path in _python_files(project.source_root):
        if path.name in EXEMPT_FILENAMES or path.name.startswith("test_"):
            continue
        for name in _private_functions(path):
            by_directory[path.parent][name].append(path)
    rows: list[tuple[str, str, str, str]] = []
    for directory, function_map in sorted(by_directory.items()):
        for name, files in sorted(function_map.items()):
            if len(files) < 2:
                continue
            rows.append(
                (
                    _rel(directory),
                    name,
                    ",".join(_rel(path) for path in sorted(files)),
                    "existing duplicate private helper ratchet",
                )
            )
    return rows


def check_helper_duplicates(project: ProjectInfo) -> list[str]:
    current = set(_helper_duplicate_rows(project))
    baseline = _load_tsv(HELPER_DUPLICATES_BASELINE, 4)
    return _compare_baseline(
        name="duplicate_helper",
        current=current,
        baseline=baseline,
        render=lambda row: f"{row[0]} {row[1]} in {row[2]}",
    )


def _filename_underscore_rows(project: ProjectInfo) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    for root in _scan_roots(project):
        for path in _python_files(root):
            if path.name in EXEMPT_FILENAMES:
                continue
            try:
                top_level = path.relative_to(REPO_ROOT).parts[0]
            except ValueError:
                top_level = ""
            if top_level in INFO_ONLY_FILENAME_ROOTS:
                continue
            count = path.stem.count("_")
            if count > UNDERSCORE_THRESHOLD:
                rows.append((_rel(path), count))
    return sorted(rows)


def check_filename_underscore(project: ProjectInfo) -> list[str]:
    current = {(path, str(count)) for path, count in _filename_underscore_rows(project)}
    baseline = _load_tsv(FILENAME_UNDERSCORE_BASELINE, 2)
    return _compare_baseline(
        name="filename_underscore_drift",
        current=current,
        baseline=baseline,
        render=lambda row: f"{row[0]} has {row[1]} underscores",
    )


def _is_broad_exception(node: ast.ExceptHandler) -> bool:
    if isinstance(node.type, ast.Name):
        return node.type.id == "Exception"
    if isinstance(node.type, ast.Tuple):
        return any(
            isinstance(item, ast.Name) and item.id == "Exception"
            for item in node.type.elts
        )
    return False


def _is_silent_pass(node: ast.ExceptHandler) -> bool:
    return len(node.body) == 1 and isinstance(node.body[0], ast.Pass)


def _broad_exception_rows(project: ProjectInfo) -> list[tuple[str, int, int, str]]:
    rows: list[tuple[str, int, int, str]] = []
    for path in _python_files(project.source_root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        total = 0
        silent = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and _is_broad_exception(node):
                total += 1
                silent += int(_is_silent_pass(node))
        if total:
            rows.append((_rel(path), total, silent, "existing broad exception ratchet"))
    return rows


def check_broad_exception(project: ProjectInfo) -> list[str]:
    current = {
        (path, str(total), str(silent), reason)
        for path, total, silent, reason in _broad_exception_rows(project)
    }
    baseline = _load_tsv(BROAD_EXCEPTION_BASELINE, 4)
    baseline_by_path = {row[0]: row for row in baseline}
    findings: list[str] = []
    for path, total, silent, _reason in sorted(current):
        baseline_row = baseline_by_path.get(path)
        if baseline_row is None:
            findings.append(f"new_broad_exception_file: {path} has {total} handler(s)")
            continue
        if int(total) > int(baseline_row[1]):
            findings.append(
                f"broad_exception_count_grew: {path} has {total} > baseline {baseline_row[1]}"
            )
        if int(silent) > int(baseline_row[2]):
            findings.append(
                f"silent_pass_count_grew: {path} has {silent} > baseline {baseline_row[2]}"
            )
    current_paths = {row[0] for row in current}
    for path in sorted(set(baseline_by_path) - current_paths):
        findings.append(f"stale_broad_exception_baseline: {path}")
    return findings


def _parent_prefix_matches(path: Path) -> bool:
    parent = path.parent.name
    if not parent:
        return False
    stem_tokens = path.stem.split("_")
    if len(stem_tokens) <= 1:
        return False
    parent_tokens = {parent}
    if parent.endswith("s") and len(parent) > 1:
        parent_tokens.add(parent[:-1])
    return stem_tokens[0] in parent_tokens


def _path_structure_rows(project: ProjectInfo) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    repo_prefixes = {
        f"{project.import_root}_",
        f"{project.name.replace('-', '_')}_",
    }
    for path in sorted(project.source_root.rglob("*")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(project.source_root).as_posix()
        if path.is_dir():
            guidance = DEPRECATED_DIR_NAMES.get(path.name)
            if guidance:
                findings.append(
                    (f"{rel}/", f"vague folder name {path.name!r}; {guidance}")
                )
            continue
        if path.suffix != ".py" or path.name in EXEMPT_FILENAMES:
            continue
        for prefix in repo_prefixes:
            if path.stem.startswith(prefix):
                findings.append((rel, f"redundant repo prefix {prefix!r}"))
        for suffix, guidance in REDUNDANT_SUFFIX_RULES.items():
            if path.stem.endswith(suffix):
                findings.append((rel, f"redundant suffix {suffix!r}; {guidance}"))
        if _parent_prefix_matches(path):
            findings.append(
                (
                    rel,
                    "filename repeats parent owner; let the folder carry subsystem context",
                )
            )
    return sorted(findings)


def check_path_structure(project: ProjectInfo) -> list[str]:
    current = set(_path_structure_rows(project))
    baseline = _load_tsv(PATH_STRUCTURE_BASELINE, 2)
    return _compare_baseline(
        name="path_structure_drift",
        current=current,
        baseline=baseline,
        render=lambda row: f"{row[0]} - {row[1]}",
    )


def check_type_ignore(project: ProjectInfo) -> list[str]:
    findings: list[str] = []
    qualified = 0
    for path in _python_files(*_scan_roots(project)):
        try:
            tokens = tokenize.generate_tokens(path.open(encoding="utf-8").readline)
        except (OSError, UnicodeDecodeError):
            continue
        try:
            for token in (item for item in tokens if item.type == tokenize.COMMENT):
                for match in TYPE_IGNORE_RE.finditer(token.string):
                    qualifier = match.group(1)
                    if qualifier is None:
                        findings.append(
                            f"bare_type_ignore: {_rel(path)}:{token.start[0]}"
                        )
                    else:
                        qualified += len(
                            [part for part in qualifier.split(",") if part.strip()]
                        )
        except tokenize.TokenError:
            continue
    if not findings:
        print(f"type_ignore_hygiene: clean - {qualified} qualified ignore(s)")
    return findings


def _import_root(name: str) -> str:
    return name.split(".", 1)[0]


def check_public_surface(project: ProjectInfo) -> list[str]:
    forbidden = KNOWN_PACKAGE_ROOTS - {project.import_root} - project.dependency_roots
    findings: list[str] = []
    for path in _python_files(project.source_root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = _import_root(alias.name)
                    if root in forbidden:
                        findings.append(
                            f"{_rel(path)}:{node.lineno}: import {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = _import_root(node.module)
                if root in forbidden:
                    findings.append(
                        f"{_rel(path)}:{node.lineno}: from {node.module} import ..."
                    )
    return findings


CHECKS = {
    "broad-exception": check_broad_exception,
    "filename-underscore": check_filename_underscore,
    "helper-duplicates": check_helper_duplicates,
    "max-file-loc": check_max_file_loc,
    "method-loc": check_method_loc,
    "path-structure": check_path_structure,
    "public-surface": check_public_surface,
    "type-ignore": check_type_ignore,
}


def write_baselines(project: ProjectInfo) -> None:
    _write_tsv(
        MAX_FILE_LOC_BASELINE,
        "# Format: path<TAB>loc<TAB>reason",
        _max_file_loc_rows(project),
    )
    _write_tsv(
        METHOD_LOC_BASELINE,
        "# Format: path<TAB>qualname<TAB>loc<TAB>reason",
        _method_loc_rows(project),
    )
    _write_tsv(
        HELPER_DUPLICATES_BASELINE,
        "# Format: directory<TAB>function<TAB>files<TAB>reason",
        _helper_duplicate_rows(project),
    )
    _write_tsv(
        FILENAME_UNDERSCORE_BASELINE,
        "# Format: path<TAB>underscore_count",
        _filename_underscore_rows(project),
    )
    _write_tsv(
        BROAD_EXCEPTION_BASELINE,
        "# Format: path<TAB>total<TAB>silent_pass<TAB>reason",
        _broad_exception_rows(project),
    )
    _write_tsv(
        PATH_STRUCTURE_BASELINE,
        "# Format: source_relative_path<TAB>finding",
        _path_structure_rows(project),
    )


def run_checks(project: ProjectInfo, selected: list[str]) -> int:
    failed = False
    for name in selected:
        findings = CHECKS[name](project)
        if findings:
            failed = True
            print(f"{name}: {len(findings)} finding(s)", file=sys.stderr)
            for finding in findings:
                print(f"  - {finding}", file=sys.stderr)
        else:
            print(f"{name}: clean")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="append",
        choices=(*CHECKS, "all"),
        help="Run one check. Repeatable. Defaults to all.",
    )
    parser.add_argument(
        "--write-baselines",
        action="store_true",
        help="Refresh ratchet baselines from the current source tree.",
    )
    args = parser.parse_args(argv)

    project = _project_info()
    if args.write_baselines:
        write_baselines(project)
        print(f"quality_patterns: wrote baselines for {project.name}")
        return 0

    selected = args.check or ["all"]
    checks = list(CHECKS) if "all" in selected else selected
    return run_checks(project, checks)


if __name__ == "__main__":
    raise SystemExit(main())
