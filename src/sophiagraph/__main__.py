"""Standalone CLI entrypoint for the reusable ``sophiagraph`` package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from uuid import uuid4

from sophiagraph.human import HumanWorkbenchPacket
from sophiagraph.models import MemoryNamespace, MemoryRecord
from sophiagraph.storage import create_sqlite_store, default_db_path
from sophiagraph.workspace import (
    apply_workspace_import,
    build_workspace_workbench,
    initialize_workspace,
    load_workspace_status,
    render_workspace_workbench,
    workspace_note_put,
    workspace_status_to_dict,
    workspace_workbench_to_dict,
    plan_workspace_import,
)


def _seed_record() -> MemoryRecord:
    return MemoryRecord(
        id=str(uuid4()),
        scope="agent:standalone",
        type="fact",
        key="standalone-smoke",
        title="Standalone smoke",
        content={"message": "sophiagraph standalone runtime OK"},
        created_at="2026-05-22T00:00:00+00:00",
        updated_at="2026-05-22T00:00:00+00:00",
        source="validated",
        confidence=1.0,
        event_time="2026-05-22T00:00:00+00:00",
    )


def _print_payload(payload: object, *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(payload)


def _namespace_from_args(args: argparse.Namespace) -> MemoryNamespace:
    return MemoryNamespace(
        tenant_id=args.tenant_id,
        org_id=args.org_id,
        user_id=args.user_id,
        agent_id=args.agent_id,
        session_id=args.session_id,
        conversation_id=args.conversation_id,
        project_id=args.project_id,
        graph_id=args.graph_id,
    )


def _build_workspace_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="sophiagraph workspace commands")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("workspace-init")
    init_parser.add_argument("workspace")
    init_parser.add_argument("--scope", required=True)
    init_parser.add_argument("--label", default="")
    init_parser.add_argument("--vault-id", default="")
    init_parser.add_argument("--root-label", default="vault")
    init_parser.add_argument("--tombstone-missing", action="store_true")
    init_parser.add_argument("--overwrite", action="store_true")
    init_parser.add_argument("--tenant-id")
    init_parser.add_argument("--org-id")
    init_parser.add_argument("--user-id")
    init_parser.add_argument("--agent-id")
    init_parser.add_argument("--session-id")
    init_parser.add_argument("--conversation-id")
    init_parser.add_argument("--project-id")
    init_parser.add_argument("--graph-id")
    init_parser.add_argument("--json", action="store_true")

    status_parser = subparsers.add_parser("workspace-status")
    status_parser.add_argument("workspace")
    status_parser.add_argument("--json", action="store_true")

    note_parser = subparsers.add_parser("workspace-note-put")
    note_parser.add_argument("workspace")
    note_parser.add_argument("note_key")
    note_parser.add_argument("--title", required=True)
    body_group = note_parser.add_mutually_exclusive_group(required=True)
    body_group.add_argument("--body")
    body_group.add_argument("--body-file")
    note_parser.add_argument("--tag", action="append", default=[])
    note_parser.add_argument("--json", action="store_true")

    plan_parser = subparsers.add_parser("workspace-import-plan")
    plan_parser.add_argument("workspace")
    plan_parser.add_argument("source_root")
    plan_parser.add_argument("--tombstone-missing", action="store_true")
    plan_parser.add_argument("--json", action="store_true")

    apply_parser = subparsers.add_parser("workspace-import-apply")
    apply_parser.add_argument("workspace")
    apply_parser.add_argument("source_root")
    apply_parser.add_argument("--tombstone-missing", action="store_true")
    apply_parser.add_argument("--json", action="store_true")

    workbench_parser = subparsers.add_parser("workspace-workbench")
    workbench_parser.add_argument("workspace")
    workbench_parser.add_argument("--source-root")
    workbench_parser.add_argument("--include-archived", action="store_true")
    workbench_parser.add_argument("--tombstone-missing", action="store_true")
    workbench_parser.add_argument("--html-out")
    workbench_parser.add_argument("--json", action="store_true")
    return parser


def _read_note_body(args: argparse.Namespace) -> str:
    if args.body is not None:
        return args.body
    return Path(args.body_file).read_text(encoding="utf-8")


def _run_workspace_cli(argv: list[str]) -> int:
    parser = _build_workspace_parser()
    args = parser.parse_args(argv)
    command = args.command
    if command == "workspace-init":
        status = initialize_workspace(
            args.workspace,
            scope=args.scope,
            namespace=_namespace_from_args(args),
            label=args.label,
            vault_id=args.vault_id,
            root_label=args.root_label,
            tombstone_missing=args.tombstone_missing,
            overwrite=args.overwrite,
        )
        _print_payload(workspace_status_to_dict(status), json_mode=args.json)
        return 0
    if command == "workspace-status":
        status = load_workspace_status(args.workspace)
        _print_payload(workspace_status_to_dict(status), json_mode=args.json)
        return 0
    if command == "workspace-note-put":
        record = workspace_note_put(
            args.workspace,
            note_key=args.note_key,
            title=args.title,
            body=_read_note_body(args),
            tags=tuple(args.tag),
        )
        payload = {
            "record_id": record.id,
            "title": record.title,
            "updated_at": record.updated_at,
        }
        _print_payload(payload, json_mode=args.json)
        return 0
    if command == "workspace-import-plan":
        plan = plan_workspace_import(
            args.workspace,
            args.source_root,
            tombstone_missing=args.tombstone_missing or None,
        )
        payload = {
            "created_count": plan.created_count,
            "updated_count": plan.updated_count,
            "deleted_count": plan.deleted_count,
            "unchanged_count": plan.unchanged_count,
            "stale_count": plan.stale_count,
            "paths": [item.path for item in plan.items],
        }
        _print_payload(payload, json_mode=args.json)
        return 0
    if command == "workspace-import-apply":
        result = apply_workspace_import(
            args.workspace,
            args.source_root,
            tombstone_missing=args.tombstone_missing or None,
        )
        payload = {
            "created_count": result.created_count,
            "updated_count": result.updated_count,
            "deleted_count": result.deleted_count,
            "stale_count": result.stale_count,
            "manifest_file_count": len(result.manifest.files),
        }
        _print_payload(payload, json_mode=args.json)
        return 0
    if command == "workspace-workbench":
        packet: HumanWorkbenchPacket = build_workspace_workbench(
            args.workspace,
            include_archived=args.include_archived,
            source_root=args.source_root,
            tombstone_missing=args.tombstone_missing or None,
        )
        if args.json:
            _print_payload(workspace_workbench_to_dict(packet), json_mode=True)
            return 0
        html = render_workspace_workbench(
            args.workspace,
            include_archived=args.include_archived,
            source_root=args.source_root,
            tombstone_missing=args.tombstone_missing or None,
        )
        if args.html_out:
            output_path = Path(args.html_out)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(html, encoding="utf-8")
            print(output_path)
            return 0
        print(html)
        return 0
    raise SystemExit(f"unknown workspace command: {command}")


def _run_smoke_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="sophiagraph standalone smoke")
    parser.add_argument("--root", default=str(Path.cwd() / ".sophiagraph-runtime"))
    parser.add_argument("--seed", action="store_true", help="insert a sample record")
    parser.add_argument("--json", action="store_true", help="emit JSON summary")
    args = parser.parse_args(argv)

    store = create_sqlite_store(args.root)
    if args.seed and store.record_count() == 0:
        store.put_record(_seed_record())

    summary = {
        "db_path": str(default_db_path(args.root)),
        "record_count": store.record_count(),
        "candidate_count": store.candidate_count(),
    }
    if args.json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print(f"sophiagraph standalone runtime OK: {summary}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in {
        "workspace-init",
        "workspace-status",
        "workspace-note-put",
        "workspace-import-plan",
        "workspace-import-apply",
        "workspace-workbench",
    }:
        return _run_workspace_cli(args)
    return _run_smoke_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
