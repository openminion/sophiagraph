"""Stdlib HTTP transport for the bounded Sophiagraph server surface."""

from __future__ import annotations

from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from typing import Any, Mapping, cast
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from sophiagraph.models import MemoryNamespace, WorkbenchActionExecutionContext
from sophiagraph.server.backend import (
    BackendConfig,
    build_wired_registry,
    resolve_backend_store,
)
from sophiagraph.server.contracts import (
    ACTION_CONFLICT_CODE,
    ACTION_NOT_FOUND_CODE,
    ACTION_RECOVERY_REQUIRED_CODE,
    ACTION_UNSUPPORTED_CODE,
    AUTH_DENIED_CODE,
    JSONRPC_INTERNAL_ERROR,
    JSONRPC_INVALID_REQUEST,
    JSONRPC_INVALID_PARAMS,
    JSONRPC_METHOD_NOT_FOUND,
    JSONRPC_PARSE_ERROR,
    QuotaExceededError,
    QUOTA_EXCEEDED_CODE,
    REQUEST_REJECTED_CODE,
    SophiagraphServerError,
    SemanticEndpointRefusedError,
    TOOL_BACKEND_INVOCATION_FAILED_CODE,
    TOOL_BACKEND_NOT_WIRED_CODE,
    TOOL_NOT_FOUND_CODE,
    TOOL_SEMANTIC_ENDPOINT_REFUSED_CODE,
)
from sophiagraph.server.deployment import DeploymentProfile
from sophiagraph.server.runtime_hardening import (
    RuntimePolicyEngine,
    RuntimeRequestContext,
    ServerAuthConfig,
    ServerPrincipal,
)
from sophiagraph.server.service_core import to_json_dict
from sophiagraph.server.tools import BANNED_SEMANTIC_TOOL_NAMES, ToolRegistry
from sophiagraph.storage.base import SophiaGraphStore
from sophiagraph.workbench import WorkbenchActionKind, WorkbenchActionRequest
from sophiagraph.workbench_actions import (
    EXECUTABLE_WORKBENCH_ACTIONS,
    HOST_REQUIRED_WORKBENCH_ACTIONS,
    PAYLOAD_IDENTITY_KEYS,
    PREVIEW_ONLY_WORKBENCH_ACTIONS,
    REVIEW_ONLY_WORKBENCH_ACTIONS,
    execute_workbench_action,
    preview_workbench_execution,
)

_JSON = "application/json; charset=utf-8"
_MAX_BODY_BYTES = 1_048_576


@dataclass(frozen=True, slots=True)
class HttpWorkbenchConfig:
    workspace_id: str = "workspace:local"
    scope: str = "agent:local"
    namespace: MemoryNamespace = field(
        default_factory=lambda: MemoryNamespace(agent_id="local", graph_id="main")
    )
    workspace_root: str = ""
    source_root: str = ""


@dataclass(frozen=True, slots=True)
class HttpTransportConfig:
    backend: BackendConfig = field(default_factory=BackendConfig)
    host: str = "127.0.0.1"
    port: int = 8766
    allowed_origins: tuple[str, ...] = ()
    max_body_bytes: int = _MAX_BODY_BYTES
    workbench: HttpWorkbenchConfig = field(default_factory=HttpWorkbenchConfig)

    def __post_init__(self) -> None:
        if self.max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be positive")
        if "*" in self.allowed_origins:
            raise ValueError("wildcard origins are not allowed")


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    payload: dict[str, Any]


class SophiagraphHttpService:
    """Pure HTTP route owner over one shared Sophiagraph backend store."""

    def __init__(
        self,
        *,
        config: HttpTransportConfig | None = None,
        runtime: RuntimePolicyEngine | None = None,
        store: SophiaGraphStore | None = None,
        registry: ToolRegistry | None = None,
    ) -> None:
        self.config = config or HttpTransportConfig()
        self.store = store or resolve_backend_store(self.config.backend)
        self.registry = registry or build_wired_registry(
            self.config.backend,
            store=self.store,
        )
        self.runtime = runtime or RuntimePolicyEngine(
            backend_name=self.config.backend.backend,
            auth=ServerAuthConfig(),
            deployment_profile=DeploymentProfile(
                allowed_transports=("http",),
                require_request_id=False,
                require_auth=False,
                max_request_bytes=self.config.max_body_bytes + 2_048,
            ),
        )

    def handle(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes = b"",
    ) -> HttpResponse:
        headers = headers or {}
        request_id = _request_id(headers)
        context = _runtime_context(method, path, headers, request_id=request_id)
        origin_error = self._origin_error(method, headers, request_id)
        if origin_error is not None:
            return origin_error
        parsed = urlparse(path)
        payload_result = self._parse_body(body, request_id=request_id)
        if isinstance(payload_result, HttpResponse):
            return payload_result
        try:
            self.runtime.enforce_deployment(
                {"id": request_id, "method": path, "body": payload_result},
                context,
            )
            principal = self.runtime.resolve_principal(context)
            quota = self.runtime.consume_quota(context)
        except QuotaExceededError as exc:
            return _error_response(exc.code, str(exc), exc.details, request_id)
        except SophiagraphServerError as exc:
            return _error_response(exc.code, str(exc), exc.details, request_id)
        try:
            response = self._route(
                method.upper(),
                parsed.path,
                parse_qs(parsed.query),
                payload_result,
                principal=principal,
                request_id=request_id,
            )
        except SophiagraphServerError as exc:
            return _error_response(exc.code, str(exc), exc.details, request_id)
        except (KeyError, TypeError, ValueError) as exc:
            return _error_response(
                JSONRPC_INVALID_PARAMS,
                str(exc),
                {},
                request_id,
            )
        if quota is not None:
            response.payload["quota"] = to_json_dict(quota)
        response.payload.setdefault("request_id", request_id)
        return response

    def _route(
        self,
        method: str,
        path: str,
        query: dict[str, list[str]],
        body: dict[str, Any],
        *,
        principal: ServerPrincipal,
        request_id: str,
    ) -> HttpResponse:
        banned = _banned_route_name(path)
        if banned:
            raise SemanticEndpointRefusedError(banned)
        if method == "GET" and path == "/health":
            return HttpResponse(
                200,
                {
                    "health": to_json_dict(
                        self.runtime.health_report(
                            request_id=request_id,
                            registry_size=len(self.registry.names()),
                        )
                    )
                },
            )
        if method == "GET" and path == "/ready":
            report = self.runtime.health_report(
                request_id=request_id,
                registry_size=len(self.registry.names()),
            )
            return HttpResponse(200, {"ready": report.ready})
        if method == "GET" and path == "/v1/workbench/capabilities":
            return HttpResponse(200, {"capabilities": self._workbench_capabilities()})
        if method == "POST" and path == "/v1/workbench/actions/preview":
            request, context = self._action_request(body, principal, request_id)
            return HttpResponse(
                200,
                {"result": preview_workbench_execution(request, context).to_dict()},
            )
        if method == "POST" and path == "/v1/workbench/actions/execute":
            request, context = self._action_request(body, principal, request_id)
            self._ensure_principal_scope(principal, context)
            result = execute_workbench_action(self.store, request, context)
            return HttpResponse(
                _status_for_action_result(result),
                {"result": result.to_dict()},
            )
        if method == "GET" and path.startswith("/v1/workbench/actions/"):
            action_id = path.rsplit("/", 1)[-1]
            entry = self.store.get_workbench_action(
                action_id,
                scope=self.config.workbench.scope,
                namespace=self.config.workbench.namespace,
            )
            if entry is None:
                return _error_response(
                    ACTION_NOT_FOUND_CODE,
                    "scoped action journal entry not found",
                    {"action_id": action_id},
                    request_id,
                )
            return HttpResponse(200, {"entry": entry.to_dict()})
        core = self._core_route(method, path, query, body)
        if core is not None:
            return core
        return _error_response(
            JSONRPC_METHOD_NOT_FOUND,
            f"route {method} {path!r} is not supported",
            {},
            request_id,
        )

    def _core_route(
        self,
        method: str,
        path: str,
        query: dict[str, list[str]],
        body: dict[str, Any],
    ) -> HttpResponse | None:
        del query
        if method == "GET" and path == "/v1/knowledge/capabilities":
            return HttpResponse(
                200,
                dict(self.registry.get_handler("knowledge_capabilities")()),
            )
        if method == "PUT" and path.startswith("/v1/knowledge/records/"):
            record_id = path.rsplit("/", 1)[-1]
            record = dict(body)
            record.setdefault("id", record_id)
            if record["id"] != record_id:
                raise ValueError("record id must match route record_id")
            return HttpResponse(
                200,
                dict(self.registry.get_handler("knowledge_put_record")(record=record)),
            )
        if method == "GET" and path.startswith("/v1/knowledge/records/"):
            if path.endswith("/relations"):
                record_id = path.removesuffix("/relations").rsplit("/", 1)[-1]
                return HttpResponse(
                    200,
                    dict(
                        self.registry.get_handler("knowledge_list_relations")(
                            record_id=record_id,
                            filters={},
                        )
                    ),
                )
            record_id = path.rsplit("/", 1)[-1]
            return HttpResponse(
                200,
                dict(
                    self.registry.get_handler("knowledge_get_record")(
                        record_id=record_id
                    )
                ),
            )
        if method == "POST" and path == "/v1/knowledge/records/list":
            return HttpResponse(
                200,
                dict(self.registry.get_handler("knowledge_list_records")(filters=body)),
            )
        if method == "POST" and path == "/v1/knowledge/records/search":
            return HttpResponse(
                200,
                dict(self.registry.get_handler("knowledge_search_records")(query=body)),
            )
        if method == "POST" and path == "/v1/knowledge/snapshots/export":
            return HttpResponse(
                200,
                dict(
                    self.registry.get_handler("knowledge_export_snapshot")(options=body)
                ),
            )
        if method == "POST" and path == "/v1/knowledge/snapshots/import":
            return HttpResponse(
                200,
                dict(
                    self.registry.get_handler("knowledge_import_snapshot")(
                        bundle=body.get("bundle") or {},
                        options=body.get("options") or {},
                    )
                ),
            )
        return None

    def _action_request(
        self,
        body: dict[str, Any],
        principal: ServerPrincipal,
        request_id: str,
    ) -> tuple[WorkbenchActionRequest, WorkbenchActionExecutionContext]:
        identity_keys = sorted(set(body) & PAYLOAD_IDENTITY_KEYS)
        if identity_keys:
            raise SophiagraphServerError(
                "HTTP workbench actions cannot carry identity or scope fields",
                code=AUTH_DENIED_CODE,
                details={
                    "reason": "payload_identity_not_allowed",
                    "fields": identity_keys,
                },
            )
        action_id = str(body.get("action_id") or "").strip()
        action = str(body.get("action") or "").strip()
        target_id = str(body.get("target_id") or "").strip()
        if not action_id or not action or not target_id:
            raise ValueError("action_id, action, and target_id are required")
        if action not in self._all_workbench_actions():
            raise SophiagraphServerError(
                "workbench action is not supported",
                code=ACTION_UNSUPPORTED_CODE,
                details={"action": action},
            )
        payload = body.get("payload") or {}
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        context = WorkbenchActionExecutionContext(
            action_id=action_id,
            request_id=request_id,
            principal_id=principal.principal_id,
            workspace_id=self.config.workbench.workspace_id,
            scope=self.config.workbench.scope,
            namespace=self.config.workbench.namespace,
            workspace_root=self.config.workbench.workspace_root,
            source_root=self.config.workbench.source_root,
            expected_updated_at=_optional_string(body.get("expected_updated_at")),
            expected_content_sha256=_optional_string(
                body.get("expected_content_sha256")
            ),
        )
        return (
            WorkbenchActionRequest(
                action=cast(WorkbenchActionKind, action),
                target_id=target_id,
                actor_id=principal.principal_id,
                workspace_id=self.config.workbench.workspace_id,
                payload_kind=str(body.get("payload_kind") or "workbench_action"),
                payload=payload,
            ),
            context,
        )

    def _workbench_capabilities(self) -> dict[str, Any]:
        return {
            "executable": sorted(EXECUTABLE_WORKBENCH_ACTIONS),
            "preview_only": sorted(PREVIEW_ONLY_WORKBENCH_ACTIONS),
            "host_required": sorted(HOST_REQUIRED_WORKBENCH_ACTIONS),
            "review_only": sorted(REVIEW_ONLY_WORKBENCH_ACTIONS),
        }

    def _all_workbench_actions(self) -> frozenset[str]:
        return frozenset(
            EXECUTABLE_WORKBENCH_ACTIONS
            | PREVIEW_ONLY_WORKBENCH_ACTIONS
            | HOST_REQUIRED_WORKBENCH_ACTIONS
            | REVIEW_ONLY_WORKBENCH_ACTIONS
        )

    def _origin_error(
        self,
        method: str,
        headers: Mapping[str, str],
        request_id: str,
    ) -> HttpResponse | None:
        if method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None
        origin = headers.get("Origin") or headers.get("origin") or ""
        if not origin or origin in self.config.allowed_origins:
            return None
        return _error_response(
            REQUEST_REJECTED_CODE,
            "origin is not allowed",
            {"request_id": request_id, "reason": "origin_not_allowed"},
            request_id,
        )

    def _parse_body(
        self,
        body: bytes,
        *,
        request_id: str,
    ) -> dict[str, Any] | HttpResponse:
        if len(body) > self.config.max_body_bytes:
            return _error_response(
                REQUEST_REJECTED_CODE,
                "request body is too large",
                {"request_id": request_id, "reason": "body_too_large"},
                request_id,
            )
        if not body:
            return {}
        try:
            parsed = json.loads(body.decode("utf-8"))
        except UnicodeDecodeError:
            return _error_response(
                JSONRPC_PARSE_ERROR,
                "request body must be utf-8 JSON",
                {},
                request_id,
            )
        except json.JSONDecodeError as exc:
            return _error_response(
                JSONRPC_PARSE_ERROR,
                f"invalid JSON: {exc.msg}",
                {},
                request_id,
            )
        if not isinstance(parsed, dict):
            return _error_response(
                JSONRPC_INVALID_PARAMS,
                "request body must be a JSON object",
                {},
                request_id,
            )
        return parsed

    def _ensure_principal_scope(
        self,
        principal: ServerPrincipal,
        context: WorkbenchActionExecutionContext,
    ) -> None:
        namespace_key = _namespace_key(context.namespace)
        if principal.allowed_scopes and context.scope not in principal.allowed_scopes:
            raise SophiagraphServerError(
                "principal is outside the allowed scope",
                code=AUTH_DENIED_CODE,
                details={"reason": "scope_not_allowed"},
            )
        if principal.allowed_namespaces and namespace_key not in (
            principal.allowed_namespaces
        ):
            raise SophiagraphServerError(
                "principal is outside the allowed namespace",
                code=AUTH_DENIED_CODE,
                details={"reason": "namespace_not_allowed"},
            )
        if principal.allowed_workspaces and context.workspace_id not in (
            principal.allowed_workspaces
        ):
            raise SophiagraphServerError(
                "principal is outside the allowed workspace",
                code=AUTH_DENIED_CODE,
                details={"reason": "workspace_not_allowed"},
            )


class SophiagraphHttpServer(ThreadingHTTPServer):
    service: SophiagraphHttpService
    url: str


def make_http_server(
    *,
    config: HttpTransportConfig | None = None,
    runtime: RuntimePolicyEngine | None = None,
) -> SophiagraphHttpServer:
    resolved = config or HttpTransportConfig()
    _validate_http_exposure(resolved, runtime)
    service = SophiagraphHttpService(config=resolved, runtime=runtime)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._handle()

        def do_POST(self) -> None:
            self._handle()

        def do_PUT(self) -> None:
            self._handle()

        def _handle(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send(
                    _error_response(
                        JSONRPC_INVALID_PARAMS,
                        "Content-Length must be numeric",
                        {},
                        _request_id(self.headers),
                    )
                )
                return
            body = self.rfile.read(length) if length else b""
            response = self.server.service.handle(
                self.command,
                self.path,
                headers={key: value for key, value in self.headers.items()},
                body=body,
            )
            self._send(response)

        def _send(self, response: HttpResponse) -> None:
            body = json.dumps(response.payload, sort_keys=True, default=str).encode(
                "utf-8"
            )
            self.send_response(response.status)
            self.send_header("Content-Type", _JSON)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = SophiagraphHttpServer((resolved.host, resolved.port), Handler)
    server.service = service
    host, port = server.server_address
    server.url = f"http://{host}:{port}"
    return server


def _validate_http_exposure(
    config: HttpTransportConfig,
    runtime: RuntimePolicyEngine | None,
) -> None:
    try:
        loopback = ipaddress.ip_address(config.host).is_loopback
    except ValueError:
        loopback = config.host == "localhost"
    auth_mode = runtime.auth.mode if runtime is not None else "none"
    if not loopback and auth_mode == "none":
        raise ValueError("non-loopback HTTP requires authentication")


def _runtime_context(
    method: str,
    path: str,
    headers: Mapping[str, str],
    *,
    request_id: str,
) -> RuntimeRequestContext:
    return RuntimeRequestContext(
        request_id=request_id,
        method=f"{method.upper()} {path}",
        transport="http",
        auth_token=_auth_token(headers),
        tenant_key=headers.get("X-Sophiagraph-Tenant"),
        namespace_key=headers.get("X-Sophiagraph-Namespace"),
    )


def _request_id(headers: Mapping[str, str]) -> str:
    return str(headers.get("X-Request-Id") or headers.get("x-request-id") or uuid4())


def _auth_token(headers: Mapping[str, str]) -> str | None:
    raw = headers.get("Authorization") or headers.get("authorization")
    if not raw:
        return None
    value = raw.strip()
    return value[7:].strip() if value.lower().startswith("bearer ") else value


def _status_for_action_result(result: Any) -> int:
    if result.outcome in {"applied", "preview_only", "queued_for_review"}:
        return 200
    if result.outcome == "conflict":
        return 409
    if result.outcome == "not_found":
        return 404
    if result.outcome == "unsupported":
        return 422
    if result.outcome == "recovery_required":
        return 409
    return (
        403 if result.reason_code in {"scope_denied", "impersonation_denied"} else 400
    )


def _error_response(
    code: int,
    message: str,
    details: Mapping[str, Any],
    request_id: str,
) -> HttpResponse:
    return HttpResponse(
        _http_status(code, details),
        {
            "error": {
                "code": int(code),
                "message": message,
                "data": dict(details),
            },
            "request_id": request_id,
        },
    )


def _http_status(code: int, details: Mapping[str, Any]) -> int:
    if code == REQUEST_REJECTED_CODE and details.get("reason") == "body_too_large":
        return 413
    mapping = {
        JSONRPC_PARSE_ERROR: 400,
        JSONRPC_INVALID_REQUEST: 400,
        JSONRPC_INVALID_PARAMS: 400,
        JSONRPC_METHOD_NOT_FOUND: 404,
        JSONRPC_INTERNAL_ERROR: 500,
        TOOL_NOT_FOUND_CODE: 404,
        TOOL_BACKEND_NOT_WIRED_CODE: 503,
        TOOL_SEMANTIC_ENDPOINT_REFUSED_CODE: 403,
        TOOL_BACKEND_INVOCATION_FAILED_CODE: 500,
        ACTION_CONFLICT_CODE: 409,
        ACTION_NOT_FOUND_CODE: 404,
        ACTION_UNSUPPORTED_CODE: 422,
        ACTION_RECOVERY_REQUIRED_CODE: 409,
        QUOTA_EXCEEDED_CODE: 429,
        REQUEST_REJECTED_CODE: 403,
    }
    if code == AUTH_DENIED_CODE:
        return (
            401 if details.get("reason") == "missing_or_invalid_bearer_token" else 403
        )
    return mapping.get(code, 500)


def _banned_route_name(path: str) -> str:
    tail = path.rsplit("/", 1)[-1]
    if tail in BANNED_SEMANTIC_TOOL_NAMES:
        return tail
    candidate = f"knowledge_{tail}"
    return candidate if candidate in BANNED_SEMANTIC_TOOL_NAMES else ""


def _namespace_key(namespace: MemoryNamespace) -> str:
    return "|".join(f"{key}={value}" for key, value in namespace.as_dict().items())


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "HttpResponse",
    "HttpTransportConfig",
    "HttpWorkbenchConfig",
    "SophiagraphHttpServer",
    "SophiagraphHttpService",
    "make_http_server",
]
