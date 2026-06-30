#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_NAME = "sophiagraph"
REQUIRE_SCOPE = False
ALLOWED_TYPES = ("feat", "fix", "docs", "refactor", "test", "chore", "style", "build")
SCOPE_EXAMPLES = ("ui", "workspace", "storage", "query", "docs", "release")
FORBIDDEN_SUMMARIES = {"update"}
COMMIT_PATTERN = re.compile(
    r"^(?P<type>feat|fix|docs|refactor|test|chore|style|build)"
    r"(?:\((?P<scope>[a-z0-9][a-z0-9-]*)\))?: (?P<summary>.+)$"
)


def _read_subject(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def _is_special_case(subject: str) -> bool:
    lowered = subject.lower()
    return (
        subject.startswith("Merge ")
        or subject.startswith('Revert "')
        or lowered == "initial commit"
    )


def _validate_standard_subject(subject: str) -> str | None:
    match = COMMIT_PATTERN.fullmatch(subject)
    if match is None:
        return None
    summary = match.group("summary").strip()
    scope = match.group("scope")
    if REQUIRE_SCOPE and not scope:
        return f"{REPO_NAME} commits must include a scope."
    if summary.lower() in FORBIDDEN_SUMMARIES:
        return "Commit summary is too vague."
    return ""


def _validate_subject(subject: str) -> str | None:
    if not subject:
        return "Commit message is empty."
    if _is_special_case(subject):
        return ""
    for prefix in ("fixup! ", "squash! "):
        if subject.startswith(prefix):
            return _validate_subject(subject[len(prefix) :].strip())
    result = _validate_standard_subject(subject)
    if result == "":
        return ""
    if result is not None:
        return result
    return "Commit message must match the documented workspace format."


def _usage_message() -> str:
    allowed_types = ", ".join(ALLOWED_TYPES)
    scope_examples = ", ".join(SCOPE_EXAMPLES)
    return (
        "Allowed formats:\n"
        "  <type>: <summary>\n"
        "  <type>(<scope>): <summary>\n\n"
        f"Allowed types: {allowed_types}\n"
        f"Scope examples: {scope_examples}\n"
        'Special cases allowed: Merge..., Revert "...", Initial commit, fixup!, squash!\n\n'
        "Examples:\n"
        "  docs: explain hook installation\n"
        "  feat(workspace): add saved-view rollups"
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("commit_message_file", nargs="?")
    parser.add_argument("--subject")
    args = parser.parse_args(argv[1:])
    if bool(args.commit_message_file) == bool(args.subject):
        parser.error("pass exactly one of <commit-message-file> or --subject")
    return args


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    subject = args.subject or _read_subject(Path(args.commit_message_file))
    error = _validate_subject(subject)
    if error == "":
        return 0
    print(error, file=sys.stderr)
    print("", file=sys.stderr)
    print(_usage_message(), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
