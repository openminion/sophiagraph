"""Typed runtime hardening primitives for auth, quotas, health, and webhooks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Final, Literal, Mapping

from sophiagraph.server.contracts import AuthDeniedError, QuotaExceededError


ServerAuthMode = Literal["none", "static_bearer"]
QuotaScope = Literal["server", "tenant", "namespace"]
HealthStatus = Literal["ok", "degraded", "failed"]
WebhookDeliveryStatus = Literal["delivered", "failed", "skipped"]

_PUBLIC_METHODS: Final[frozenset[str]] = frozenset(
    {
        "initialize",
        "initialized",
        "notifications/initialized",
        "ping",
        "runtime/health",
        "runtime/ready",
    }
)


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@dataclass(frozen=True, slots=True)
class ServerAuthConfig:
    mode: ServerAuthMode = "none"
    static_tokens: tuple[str, ...] = ()
    unauthenticated_methods: tuple[str, ...] = tuple(sorted(_PUBLIC_METHODS))

    def __post_init__(self) -> None:
        if self.mode not in {"none", "static_bearer"}:
            raise ValueError(f"invalid auth mode: {self.mode!r}")
        if self.mode == "static_bearer" and not self.static_tokens:
            raise ValueError("static_bearer auth requires at least one token")


@dataclass(frozen=True, slots=True)
class QuotaRule:
    rule_id: str
    max_requests: int
    window_seconds: int
    scope: QuotaScope = "server"

    def __post_init__(self) -> None:
        if not self.rule_id:
            raise ValueError("rule_id is required")
        if self.max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if self.scope not in {"server", "tenant", "namespace"}:
            raise ValueError(f"invalid quota scope: {self.scope!r}")


@dataclass(frozen=True, slots=True)
class RuntimeRequestContext:
    request_id: str
    method: str
    transport: str
    auth_token: str | None = None
    tenant_key: str | None = None
    namespace_key: str | None = None
    tool_name: str | None = None


@dataclass(frozen=True, slots=True)
class QuotaUsageSnapshot:
    rule_id: str
    scope_key: str
    used_requests: int
    remaining_requests: int
    window_seconds: int
    reset_at: str


@dataclass(frozen=True, slots=True)
class RuntimeHealthComponent:
    name: str
    status: HealthStatus
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RuntimeHealthReport:
    status: HealthStatus
    ready: bool
    request_id: str | None = None
    components: tuple[RuntimeHealthComponent, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WebhookSubscription:
    subscription_id: str
    event_types: tuple[str, ...]
    active: bool = True
    endpoint_label: str | None = None
    secret: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeEventEnvelope:
    event_id: str
    event_type: str
    occurred_at: str
    request_id: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WebhookDeliveryAttempt:
    subscription_id: str
    event_id: str
    status: WebhookDeliveryStatus
    http_status: int | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class WebhookDeliveryBatch:
    event: RuntimeEventEnvelope
    attempts: tuple[WebhookDeliveryAttempt, ...]


WebhookSender = Callable[
    [WebhookSubscription, RuntimeEventEnvelope], tuple[int, str | None]
]


def _extract_meta(message: Mapping[str, Any]) -> Mapping[str, Any]:
    raw_meta = message.get("meta")
    return raw_meta if isinstance(raw_meta, Mapping) else {}


def _extract_auth_token(meta: Mapping[str, Any]) -> str | None:
    for key in ("authorization", "bearer_token", "auth_token"):
        raw = meta.get(key)
        if raw is None:
            continue
        value = str(raw).strip()
        if not value:
            continue
        if value.lower().startswith("bearer "):
            return value[7:].strip()
        return value
    return None


def event_type_for_tool(tool_name: str | None) -> str | None:
    mapping = {
        "knowledge_put_record": "knowledge.record.put",
        "knowledge_export_snapshot": "knowledge.snapshot.export",
        "knowledge_import_snapshot": "knowledge.snapshot.import",
    }
    return mapping.get(tool_name or "")


@dataclass
class RuntimePolicyEngine:
    backend_name: str = "memory"
    auth: ServerAuthConfig = field(default_factory=ServerAuthConfig)
    quota: QuotaRule | None = None
    webhook_subscriptions: tuple[WebhookSubscription, ...] = ()
    webhook_sender: WebhookSender | None = None
    _quota_counters: dict[str, int] = field(default_factory=dict)
    _quota_window_started_at: dict[str, str] = field(default_factory=dict)

    def context_from_message(
        self,
        message: Mapping[str, Any],
        *,
        transport: str = "stdio",
    ) -> RuntimeRequestContext:
        meta = _extract_meta(message)
        method = str(message.get("method") or "")
        params = message.get("params")
        tool_name = None
        if method == "tools/call" and isinstance(params, Mapping):
            tool_name = str(params.get("name") or "") or None
        raw_request_id = (
            meta.get("requestId")
            or meta.get("request_id")
            or message.get("id")
            or f"{method or 'notification'}-notification"
        )
        tenant_value = meta.get("tenant") or meta.get("tenant_id")
        namespace_value = meta.get("namespace")
        return RuntimeRequestContext(
            request_id=str(raw_request_id),
            method=method,
            transport=transport,
            auth_token=_extract_auth_token(meta),
            tenant_key=str(tenant_value) if tenant_value is not None else None,
            namespace_key=str(namespace_value) if namespace_value is not None else None,
            tool_name=tool_name,
        )

    def authorize(self, context: RuntimeRequestContext) -> None:
        if self.auth.mode == "none":
            return
        if context.method in self.auth.unauthenticated_methods:
            return
        if context.auth_token and context.auth_token in self.auth.static_tokens:
            return
        raise AuthDeniedError(
            request_id=context.request_id,
            reason="missing_or_invalid_bearer_token",
            auth_mode=self.auth.mode,
        )

    def consume_quota(
        self, context: RuntimeRequestContext
    ) -> QuotaUsageSnapshot | None:
        if self.quota is None:
            return None
        scope_key = self._scope_key(context, self.quota.scope)
        started_at = self._quota_window_started_at.get(scope_key, _utc_now_iso())
        used = self._quota_counters.get(scope_key, 0)
        if used >= self.quota.max_requests:
            raise QuotaExceededError(
                request_id=context.request_id,
                rule_id=self.quota.rule_id,
                scope_key=scope_key,
                used_requests=used,
                max_requests=self.quota.max_requests,
            )
        used += 1
        self._quota_counters[scope_key] = used
        self._quota_window_started_at[scope_key] = started_at
        remaining = max(self.quota.max_requests - used, 0)
        return QuotaUsageSnapshot(
            rule_id=self.quota.rule_id,
            scope_key=scope_key,
            used_requests=used,
            remaining_requests=remaining,
            window_seconds=self.quota.window_seconds,
            reset_at=started_at,
        )

    def health_report(
        self,
        *,
        request_id: str | None,
        registry_size: int,
    ) -> RuntimeHealthReport:
        components = (
            RuntimeHealthComponent(
                name="backend",
                status="ok",
                detail={"backend": self.backend_name},
            ),
            RuntimeHealthComponent(
                name="auth",
                status="ok",
                detail={"mode": self.auth.mode},
            ),
            RuntimeHealthComponent(
                name="quota",
                status="ok" if self.quota is not None else "degraded",
                detail=(
                    {
                        "rule_id": self.quota.rule_id,
                        "max_requests": self.quota.max_requests,
                        "window_seconds": self.quota.window_seconds,
                        "scope": self.quota.scope,
                    }
                    if self.quota is not None
                    else {"configured": False}
                ),
            ),
            RuntimeHealthComponent(
                name="webhooks",
                status="ok" if self.webhook_subscriptions else "degraded",
                detail={
                    "subscription_count": len(
                        [sub for sub in self.webhook_subscriptions if sub.active]
                    )
                },
            ),
            RuntimeHealthComponent(
                name="registry",
                status="ok",
                detail={"tool_count": registry_size},
            ),
        )
        ready = True
        return RuntimeHealthReport(
            status="ok",
            ready=ready,
            request_id=request_id,
            components=components,
            diagnostics={
                "backend": self.backend_name,
                "auth_mode": self.auth.mode,
                "quota_enabled": self.quota is not None,
                "registry_size": registry_size,
            },
        )

    def deliver_tool_event(
        self,
        context: RuntimeRequestContext,
        payload: Mapping[str, Any],
    ) -> WebhookDeliveryBatch | None:
        event_type = event_type_for_tool(context.tool_name)
        if event_type is None:
            return None
        event = RuntimeEventEnvelope(
            event_id=f"{context.request_id}:{event_type}",
            event_type=event_type,
            occurred_at=_utc_now_iso(),
            request_id=context.request_id,
            payload=dict(payload),
        )
        attempts: list[WebhookDeliveryAttempt] = []
        for subscription in self.webhook_subscriptions:
            if not subscription.active:
                attempts.append(
                    WebhookDeliveryAttempt(
                        subscription_id=subscription.subscription_id,
                        event_id=event.event_id,
                        status="skipped",
                        error="inactive",
                    )
                )
                continue
            if (
                "*" not in subscription.event_types
                and event.event_type not in subscription.event_types
            ):
                attempts.append(
                    WebhookDeliveryAttempt(
                        subscription_id=subscription.subscription_id,
                        event_id=event.event_id,
                        status="skipped",
                        error="event_not_subscribed",
                    )
                )
                continue
            if self.webhook_sender is None:
                attempts.append(
                    WebhookDeliveryAttempt(
                        subscription_id=subscription.subscription_id,
                        event_id=event.event_id,
                        status="skipped",
                        error="no_sender_configured",
                    )
                )
                continue
            http_status, error = self.webhook_sender(subscription, event)
            delivered = 200 <= int(http_status) < 300 and error is None
            attempts.append(
                WebhookDeliveryAttempt(
                    subscription_id=subscription.subscription_id,
                    event_id=event.event_id,
                    status="delivered" if delivered else "failed",
                    http_status=int(http_status),
                    error=error,
                )
            )
        return WebhookDeliveryBatch(event=event, attempts=tuple(attempts))

    @staticmethod
    def _scope_key(context: RuntimeRequestContext, scope: QuotaScope) -> str:
        if scope == "server":
            return "server"
        if scope == "tenant":
            return context.tenant_key or "tenant:unknown"
        return context.namespace_key or "namespace:unknown"


__all__ = [
    "HealthStatus",
    "QuotaRule",
    "QuotaScope",
    "QuotaUsageSnapshot",
    "RuntimeEventEnvelope",
    "RuntimeHealthComponent",
    "RuntimeHealthReport",
    "RuntimePolicyEngine",
    "RuntimeRequestContext",
    "ServerAuthConfig",
    "ServerAuthMode",
    "WebhookDeliveryAttempt",
    "WebhookDeliveryBatch",
    "WebhookDeliveryStatus",
    "WebhookSubscription",
    "event_type_for_tool",
]
