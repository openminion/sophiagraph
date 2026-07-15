"""CLI entrypoint for the in-package `sophiagraph-server` runtime."""

from __future__ import annotations

import argparse
import sys

from sophiagraph.server.backend import BackendConfig, build_wired_registry
from sophiagraph.server.deployment import DeploymentProfile
from sophiagraph.server.runtime_hardening import (
    QuotaRule,
    RuntimePolicyEngine,
    ServerAuthConfig,
)
from sophiagraph.server.server import ServerInfo, serve_stdio
from sophiagraph.server.tools import ToolRegistry

_BACKENDS = ("memory", "sqlite")
_AUTH_MODES = ("none", "static_bearer")
_QUOTA_SCOPES = ("server", "tenant", "namespace")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sophiagraph-server")
    subparsers = parser.add_subparsers(dest="command")
    _stdio_help = (
        "Run the bounded MCP runtime over stdio. Data tools use the selected "
        "backend by default; --no-wire-backend keeps a contract-only registry."
    )
    stdio_parser = subparsers.add_parser(
        "serve-stdio",
        help=_stdio_help,
        description=_stdio_help,
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
    stdio_parser.add_argument(
        "--production",
        action="store_true",
        help="Require auth, quotas, request ids, and bounded request size.",
    )
    stdio_parser.add_argument(
        "--max-request-bytes",
        type=int,
        default=1_048_576,
        help="Maximum encoded request size (default: 1048576).",
    )
    stdio_parser.add_argument(
        "--auth-mode",
        choices=_AUTH_MODES,
        default="none",
        help="Runtime auth posture (default: none).",
    )
    stdio_parser.add_argument(
        "--bearer-token",
        dest="bearer_tokens",
        action="append",
        default=[],
        help="Static bearer token accepted when --auth-mode static_bearer is used. Repeatable.",
    )
    stdio_parser.add_argument(
        "--quota-max-requests",
        type=int,
        default=None,
        help="Optional max requests per quota window.",
    )
    stdio_parser.add_argument(
        "--quota-window-seconds",
        type=int,
        default=60,
        help="Quota window size in seconds (default: 60).",
    )
    stdio_parser.add_argument(
        "--quota-scope",
        choices=_QUOTA_SCOPES,
        default="server",
        help="Quota scope when quota is enabled (default: server).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "serve-stdio":
        if args.auth_mode == "static_bearer" and not args.bearer_tokens:
            parser.error(
                "--auth-mode static_bearer requires at least one --bearer-token"
            )
        if args.production and (
            args.auth_mode == "none" or args.quota_max_requests is None
        ):
            parser.error(
                "--production requires static bearer auth and --quota-max-requests"
            )
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
            quota=(
                QuotaRule(
                    rule_id="stdio-default",
                    max_requests=args.quota_max_requests,
                    window_seconds=args.quota_window_seconds,
                    scope=args.quota_scope,
                )
                if args.quota_max_requests is not None
                else None
            ),
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
    parser.print_help(sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
