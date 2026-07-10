"""CLI entrypoint for the in-package `sophiagraph-server` runtime command.

KMSR-01 wires `serve-stdio` to the bounded MCP v1 surface defined in
`sophiagraph.server.tools` and `sophiagraph.server.server`.

KMSR-02 adds the `--wire-backend` flag (default ON) that swaps the
`BackendNotWiredError` stub handlers for real `sophiagraph` store
invocations via `sophiagraph.server.backend.build_wired_registry`. Pass
`--no-wire-backend` to keep the KMSR-01 stub registry (useful for contract
testing or contract-only demos).
"""

from __future__ import annotations

import argparse
import sys

from sophiagraph.server.backend import BackendConfig, build_wired_registry
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
        "Run the bounded KMSR v1 MCP runtime over stdio. With --wire-backend "
        "(default), data-op tools execute against the selected sophiagraph "
        "backend (KMSR-02). With --no-wire-backend, data-op tools raise "
        "BackendNotWiredError (KMSR-01 stub registry)."
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
        help="Wire data-op handlers to the live sophiagraph store (KMSR-02 default).",
    )
    stdio_parser.add_argument(
        "--no-wire-backend",
        dest="wire_backend",
        action="store_false",
        help="Use the KMSR-01 stub registry (data ops raise BackendNotWiredError).",
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
