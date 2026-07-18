"""CLI entrypoint for the in-package `sophiagraph-server` runtime."""

from __future__ import annotations

import argparse
import json
import sys

from sophiagraph.graph_backends import FakeGraphBackendAdapter
from sophiagraph.models import MemoryNamespace, ProjectionTarget
from sophiagraph.projection import (
    GraphChangeProjector,
    VectorChangeProjector,
    get_projection_health,
    run_projection_batch,
)
from sophiagraph.projection_reconciliation import (
    apply_projection_repair_plan,
    canonical_projection_inventory,
    reconcile_projection_target,
)
from sophiagraph.server.backend import (
    BackendConfig,
    build_wired_registry,
    resolve_backend_store,
)
from sophiagraph.server.deployment import DeploymentProfile
from sophiagraph.server.http import (
    HttpTransportConfig,
    HttpWorkbenchConfig,
    make_http_server,
)
from sophiagraph.server.runtime_hardening import (
    QuotaRule,
    RuntimePolicyEngine,
    ServerAuthConfig,
    ServerPrincipal,
)
from sophiagraph.server.server import ServerInfo, serve_stdio
from sophiagraph.server.service_core import to_json_dict
from sophiagraph.server.tools import ToolRegistry
from sophiagraph.temporal import utc_now_iso
from sophiagraph.vector_backends import FakeVectorBackend
from sophiagraph.workbench_actions import prune_workbench_action_journal

_BACKENDS = ("memory", "sqlite")
_AUTH_MODES = ("none", "static_bearer")
_QUOTA_SCOPES = ("server", "tenant", "namespace")
_PROJECTION_KINDS = ("graph", "vector")


def _add_backend_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--backend",
        choices=_BACKENDS,
        default="sqlite",
        help="Backend selection (default: sqlite)",
    )
    parser.add_argument(
        "--sqlite-path",
        default=None,
        help="On-disk path for sqlite backend (defaults to sophiagraph.default_db_path)",
    )


def _add_namespace_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--tenant-id", default=None, help="Optional namespace tenant id."
    )
    parser.add_argument("--agent-id", default="local", help="Namespace agent id.")
    parser.add_argument("--graph-id", default="main", help="Namespace graph id.")


def _add_projection_args(parser: argparse.ArgumentParser) -> None:
    _add_backend_args(parser)
    _add_namespace_args(parser)
    parser.add_argument("--target-id", required=True, help="Projection target id.")
    parser.add_argument(
        "--target-kind",
        choices=_PROJECTION_KINDS,
        default="graph",
        help="Projection target kind when registering a fake target.",
    )
    parser.add_argument(
        "--register-fake-target",
        action="store_true",
        help="Register a missing fake projection target before running the command.",
    )
    parser.add_argument(
        "--owner-id", default="sophiagraph-server", help="Lease owner id."
    )
    parser.add_argument("--now", default="", help="Override operation timestamp.")


def _add_runtime_security_args(
    parser: argparse.ArgumentParser,
    *,
    max_request_help: str,
) -> None:
    parser.add_argument(
        "--production",
        action="store_true",
        help="Require auth, quotas, request ids, and bounded request size.",
    )
    parser.add_argument(
        "--max-request-bytes",
        type=int,
        default=1_048_576,
        help=max_request_help,
    )
    parser.add_argument(
        "--auth-mode",
        choices=_AUTH_MODES,
        default="none",
        help="Runtime auth posture (default: none).",
    )
    parser.add_argument(
        "--bearer-token",
        dest="bearer_tokens",
        action="append",
        default=[],
        help="Static bearer token accepted when --auth-mode static_bearer is used. Repeatable.",
    )
    parser.add_argument(
        "--quota-max-requests",
        type=int,
        default=None,
        help="Optional max requests per quota window.",
    )
    parser.add_argument(
        "--quota-window-seconds",
        type=int,
        default=60,
        help="Quota window size in seconds (default: 60).",
    )
    parser.add_argument(
        "--quota-scope",
        choices=_QUOTA_SCOPES,
        default="server",
        help="Quota scope when quota is enabled (default: server).",
    )


def _add_stdio_command(subparsers) -> None:
    command_help = (
        "Run the bounded MCP runtime over stdio. Data tools use the selected "
        "backend by default; --no-wire-backend keeps a contract-only registry."
    )
    stdio_parser = subparsers.add_parser(
        "serve-stdio",
        help=command_help,
        description=command_help,
    )
    stdio_parser.add_argument(
        "--backend",
        choices=_BACKENDS,
        default="memory",
        help="Backend selection (default: memory)",
    )
    stdio_parser.add_argument(
        "--sqlite-path",
        default=None,
        help="On-disk path for sqlite backend (defaults to sophiagraph.default_db_path)",
    )
    stdio_parser.add_argument(
        "--wire-backend",
        dest="wire_backend",
        action="store_true",
        default=True,
        help="Wire data handlers to the selected sophiagraph store (default).",
    )
    stdio_parser.add_argument(
        "--no-wire-backend",
        dest="wire_backend",
        action="store_false",
        help="Use a contract-only registry without a configured store.",
    )
    _add_runtime_security_args(
        stdio_parser,
        max_request_help="Maximum encoded request size (default: 1048576).",
    )


def _add_http_transport_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="HTTP bind host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8766,
        help="HTTP bind port (default: 8766)",
    )
    parser.add_argument(
        "--allowed-origin",
        dest="allowed_origins",
        action="append",
        default=[],
        help="Exact Origin value allowed for mutating browser requests. Repeatable.",
    )


def _add_http_workbench_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--principal-id",
        default="local-operator",
        help="Principal id assigned to accepted HTTP workbench actions.",
    )
    parser.add_argument(
        "--workspace-id",
        default="workspace:local",
        help="Trusted workspace id for workbench action execution.",
    )
    parser.add_argument(
        "--workspace-root",
        default="",
        help="Trusted workspace root for file-primary workbench actions.",
    )
    parser.add_argument(
        "--source-root",
        default="",
        help="Trusted source root for file-primary workbench actions.",
    )
    parser.add_argument(
        "--scope",
        default="agent:local",
        help="Sophiagraph scope for workbench action execution.",
    )
    parser.add_argument(
        "--tenant-id", default=None, help="Optional namespace tenant id."
    )
    parser.add_argument(
        "--agent-id",
        default="local",
        help="Namespace agent id (default: local).",
    )
    parser.add_argument(
        "--graph-id",
        default="main",
        help="Namespace graph id (default: main).",
    )


def _add_http_command(subparsers) -> None:
    command_help = (
        "Run the bounded HTTP REST runtime over a shared sophiagraph backend. "
        "Loopback local development can run without auth; non-loopback exposure "
        "requires bearer auth."
    )
    http_parser = subparsers.add_parser(
        "serve-http",
        help=command_help,
        description=command_help,
    )
    http_parser.add_argument(
        "--backend",
        choices=_BACKENDS,
        default="memory",
        help="Backend selection (default: memory)",
    )
    http_parser.add_argument(
        "--sqlite-path",
        default=None,
        help="On-disk path for sqlite backend (defaults to sophiagraph.default_db_path)",
    )
    _add_http_transport_args(http_parser)
    _add_runtime_security_args(
        http_parser,
        max_request_help="Maximum HTTP request body size (default: 1048576).",
    )
    _add_http_workbench_args(http_parser)


def _add_projection_commands(subparsers) -> None:
    projection_run = subparsers.add_parser(
        "projection-run",
        help="Run one projection batch and exit with a JSON report.",
    )
    _add_projection_args(projection_run)
    projection_run.add_argument(
        "--max-events",
        type=int,
        default=100,
        help="Maximum changefeed events to project in this run.",
    )
    projection_status = subparsers.add_parser(
        "projection-status",
        help="Report projection health and exit with JSON.",
    )
    _add_projection_args(projection_status)
    projection_release = subparsers.add_parser(
        "projection-release-failure",
        help="Release one projection failure for retry after explicit authorization.",
    )
    _add_projection_args(projection_release)
    projection_release.add_argument("--event-id", required=True)
    projection_release.add_argument("--authorized", action="store_true")
    projection_reconcile = subparsers.add_parser(
        "projection-reconcile",
        help="Compare canonical projection inventory with a fake target inventory.",
    )
    _add_projection_args(projection_reconcile)
    projection_reconcile.add_argument("--apply", action="store_true")
    projection_reconcile.add_argument("--authorized", action="store_true")


def _add_journal_commands(subparsers) -> None:
    journal_status = subparsers.add_parser(
        "journal-status",
        help="Report one scoped workbench action journal entry as JSON.",
    )
    _add_backend_args(journal_status)
    _add_namespace_args(journal_status)
    journal_status.add_argument("--scope", default="agent:local")
    journal_status.add_argument("--action-id", required=True)
    journal_prune = subparsers.add_parser(
        "journal-prune",
        help="Prune terminal action journal entries before a timestamp.",
    )
    _add_backend_args(journal_prune)
    journal_prune.add_argument("--completed-before", required=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sophiagraph-server")
    subparsers = parser.add_subparsers(dest="command")
    _add_stdio_command(subparsers)
    _add_http_command(subparsers)
    _add_projection_commands(subparsers)
    _add_journal_commands(subparsers)
    return parser


def _validate_runtime_args(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    if args.auth_mode == "static_bearer" and not args.bearer_tokens:
        parser.error("--auth-mode static_bearer requires at least one --bearer-token")
    if args.production and (
        args.auth_mode == "none" or args.quota_max_requests is None
    ):
        parser.error(
            "--production requires static bearer auth and --quota-max-requests"
        )


def _quota_from_args(args: argparse.Namespace) -> QuotaRule | None:
    if args.quota_max_requests is None:
        return None
    rule_prefix = "http" if args.command == "serve-http" else "stdio"
    return QuotaRule(
        rule_id=f"{rule_prefix}-default",
        max_requests=args.quota_max_requests,
        window_seconds=args.quota_window_seconds,
        scope=args.quota_scope,
    )


def _http_namespace(args: argparse.Namespace) -> MemoryNamespace:
    return MemoryNamespace(
        tenant_id=args.tenant_id,
        agent_id=args.agent_id,
        graph_id=args.graph_id,
    )


def _auth_config_from_args(args: argparse.Namespace) -> ServerAuthConfig:
    tokens = tuple(args.bearer_tokens)
    if args.auth_mode == "static_bearer" and tokens:
        namespace_key = "|".join(
            f"{key}={value}" for key, value in _http_namespace(args).as_dict().items()
        )
        principal = ServerPrincipal(
            principal_id=args.principal_id,
            allowed_scopes=(args.scope,),
            allowed_namespaces=(namespace_key,),
            allowed_workspaces=(args.workspace_id,),
        )
        return ServerAuthConfig(
            mode=args.auth_mode,
            static_tokens=tokens,
            token_principals={token: principal for token in tokens},
        )
    return ServerAuthConfig(
        mode=args.auth_mode,
        static_tokens=tokens,
        local_principal=ServerPrincipal(principal_id=args.principal_id),
    )


def _operation_now(args: argparse.Namespace) -> str:
    return str(args.now or utc_now_iso())


def _store_from_args(args: argparse.Namespace):
    return resolve_backend_store(
        BackendConfig(backend=args.backend, sqlite_path=args.sqlite_path)
    )


def _print_json(payload: object) -> None:
    print(json.dumps(to_json_dict(payload), sort_keys=True))


def _operation_error(reason: str, *, status: int = 2) -> int:
    _print_json({"ok": False, "error": {"reason": reason}})
    return status


def _ensure_projection_target(store, args: argparse.Namespace) -> ProjectionTarget:
    target = store.get_projection_target(args.target_id)
    if target is not None:
        return target
    if not args.register_fake_target:
        raise ValueError("projection target is not registered")
    kind = "vector" if args.target_kind == "vector" else "graph"
    target = ProjectionTarget(
        args.target_id,
        kind,
        "fake",
        namespace=_http_namespace(args),
    )
    store.register_projection_target(target)
    return target


def _projection_projector(store, target: ProjectionTarget):
    if target.adapter_name != "fake":
        raise ValueError("one-shot CLI currently requires adapter_name='fake'")
    if target.kind == "graph":
        adapter = FakeGraphBackendAdapter()
        return GraphChangeProjector(adapter), adapter
    adapter = FakeVectorBackend()
    return VectorChangeProjector(store, adapter), adapter


def _source_head_cursor(store, target: ProjectionTarget) -> int:
    namespaces = [target.namespace] if target.namespace is not None else None
    events = store.list_changes(namespaces=namespaces)
    return int(events[-1].cursor or 0) if events else 0


def _projection_run_cli(args: argparse.Namespace) -> int:
    try:
        store = _store_from_args(args)
        target = _ensure_projection_target(store, args)
        projector, _adapter = _projection_projector(store, target)
        report = run_projection_batch(
            store,
            target_id=args.target_id,
            projector=projector,
            owner_id=args.owner_id,
            now=_operation_now(args),
            max_events=args.max_events,
        )
    except ValueError as exc:
        return _operation_error(str(exc))
    _print_json({"ok": True, "projection": to_json_dict(report)})
    return 0


def _projection_status_cli(args: argparse.Namespace) -> int:
    try:
        store = _store_from_args(args)
        _ensure_projection_target(store, args)
        health = get_projection_health(
            store,
            target_id=args.target_id,
            now=_operation_now(args),
        )
    except ValueError as exc:
        return _operation_error(str(exc))
    _print_json({"ok": True, "health": to_json_dict(health)})
    return 0


def _projection_release_failure_cli(args: argparse.Namespace) -> int:
    if not args.authorized:
        return _operation_error("projection failure release requires authorization")
    try:
        store = _store_from_args(args)
        _ensure_projection_target(store, args)
        store.release_projection_failure(
            target_id=args.target_id,
            event_id=args.event_id,
            now=_operation_now(args),
        )
    except ValueError as exc:
        return _operation_error(str(exc))
    _print_json(
        {
            "ok": True,
            "released": {"target_id": args.target_id, "event_id": args.event_id},
        }
    )
    return 0


def _projection_reconcile_cli(args: argparse.Namespace) -> int:
    if args.apply and not args.authorized:
        return _operation_error("projection repair requires authorization")
    try:
        store = _store_from_args(args)
        target = _ensure_projection_target(store, args)
        _projector, adapter = _projection_projector(store, target)
        namespaces = [target.namespace] if target.namespace is not None else None
        source_events = store.list_changes(namespaces=namespaces)
        report, plan = reconcile_projection_target(
            target_id=args.target_id,
            source_cursor=_source_head_cursor(store, target),
            canonical_inventory=canonical_projection_inventory(
                source_events,
                target_kind=target.kind,
            ),
            target_inventory=adapter.inventory(),
            target_watermark=adapter.get_projection_watermark(),
        )
    except ValueError as exc:
        return _operation_error(str(exc))
    applied_count = 0
    if args.apply:
        applied_count = apply_projection_repair_plan(
            plan,
            expected_report_id=report.report_id,
            current_source_cursor=report.source_cursor,
            authorized=True,
            upsert=lambda _action: None,
            delete=lambda _action: None,
        )
    _print_json(
        {
            "ok": True,
            "report": to_json_dict(report),
            "plan": to_json_dict(plan),
            "applied_count": applied_count,
        }
    )
    return 0


def _journal_status_cli(args: argparse.Namespace) -> int:
    store = _store_from_args(args)
    entry = store.get_workbench_action(
        args.action_id,
        scope=args.scope,
        namespace=_http_namespace(args),
    )
    _print_json({"ok": entry is not None, "entry": to_json_dict(entry)})
    return 0 if entry is not None else 1


def _journal_prune_cli(args: argparse.Namespace) -> int:
    store = _store_from_args(args)
    pruned = prune_workbench_action_journal(
        store,
        completed_before=args.completed_before,
    )
    _print_json({"ok": True, "pruned": pruned})
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "serve-stdio":
        _validate_runtime_args(parser, args)
        if args.wire_backend:
            registry = build_wired_registry(
                BackendConfig(backend=args.backend, sqlite_path=args.sqlite_path)
            )
        else:
            registry = ToolRegistry.default(backend=args.backend)
        runtime = RuntimePolicyEngine(
            backend_name=args.backend,
            auth=ServerAuthConfig(
                mode=args.auth_mode,
                static_tokens=tuple(args.bearer_tokens),
            ),
            quota=_quota_from_args(args),
            deployment_profile=DeploymentProfile(
                profile_id="production" if args.production else "local-development",
                max_request_bytes=args.max_request_bytes,
                require_auth=args.production,
                require_request_id=args.production,
            ),
        )
        return serve_stdio(
            registry=registry,
            server_info=ServerInfo(),
            runtime=runtime,
        )
    if args.command == "serve-http":
        _validate_runtime_args(parser, args)
        config = HttpTransportConfig(
            backend=BackendConfig(backend=args.backend, sqlite_path=args.sqlite_path),
            host=args.host,
            port=args.port,
            allowed_origins=tuple(args.allowed_origins),
            max_body_bytes=args.max_request_bytes,
            workbench=HttpWorkbenchConfig(
                workspace_id=args.workspace_id,
                scope=args.scope,
                namespace=_http_namespace(args),
                workspace_root=args.workspace_root,
                source_root=args.source_root,
            ),
        )
        runtime = RuntimePolicyEngine(
            backend_name=args.backend,
            auth=_auth_config_from_args(args),
            quota=_quota_from_args(args),
            deployment_profile=DeploymentProfile(
                profile_id="production" if args.production else "local-development",
                allowed_transports=("http",),
                max_request_bytes=args.max_request_bytes + 2_048,
                require_auth=args.production,
                require_request_id=args.production,
            ),
        )
        try:
            server = make_http_server(config=config, runtime=runtime)
        except ValueError as exc:
            parser.error(str(exc))
        print(f"sophiagraph-server HTTP listening on {server.url}", file=sys.stderr)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return 0
        finally:
            server.server_close()
    if args.command == "projection-run":
        return _projection_run_cli(args)
    if args.command == "projection-status":
        return _projection_status_cli(args)
    if args.command == "projection-release-failure":
        return _projection_release_failure_cli(args)
    if args.command == "projection-reconcile":
        return _projection_reconcile_cli(args)
    if args.command == "journal-status":
        return _journal_status_cli(args)
    if args.command == "journal-prune":
        return _journal_prune_cli(args)
    parser.print_help(sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
