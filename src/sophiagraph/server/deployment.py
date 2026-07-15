"""Production deployment admission contracts for the optional server."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Mapping

from sophiagraph.server.contracts import RequestRejectedError


@dataclass(frozen=True, slots=True)
class DeploymentProfile:
    profile_id: str = "local-development"
    allowed_transports: tuple[str, ...] = ("stdio",)
    max_request_bytes: int = 1_048_576
    require_auth: bool = False
    require_request_id: bool = True

    def __post_init__(self) -> None:
        if not self.profile_id or not self.allowed_transports:
            raise ValueError("profile_id and allowed_transports are required")
        if self.max_request_bytes <= 0:
            raise ValueError("max_request_bytes must be positive")


def enforce_deployment_profile(
    profile: DeploymentProfile,
    message: Mapping[str, object],
    *,
    transport: str,
    auth_mode: str,
) -> None:
    request_id = str(message.get("id") or "notification")
    if transport not in profile.allowed_transports:
        raise RequestRejectedError(
            request_id=request_id,
            reason="transport_not_allowed",
        )
    encoded_size = len(
        json.dumps(message, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    )
    if encoded_size > profile.max_request_bytes:
        raise RequestRejectedError(request_id=request_id, reason="request_too_large")
    if profile.require_auth and auth_mode == "none":
        raise RequestRejectedError(request_id=request_id, reason="auth_required")
    if profile.require_request_id and "id" not in message:
        method = str(message.get("method") or "")
        if method not in {"initialized", "notifications/initialized"}:
            raise RequestRejectedError(
                request_id=request_id, reason="request_id_required"
            )


__all__ = ["DeploymentProfile", "enforce_deployment_profile"]
