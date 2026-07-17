"""In-memory parity implementation for projection delivery state."""

from __future__ import annotations

from dataclasses import replace

from sophiagraph.contracts.errors import (
    NotFoundError,
    ProjectionCheckpointError,
    ProjectionFenceError,
    ProjectionLeaseHeldError,
)
from sophiagraph.models import (
    MemoryNamespace,
    ProjectionAttempt,
    ProjectionCheckpoint,
    ProjectionFailure,
    ProjectionLease,
    ProjectionTarget,
)
from sophiagraph.storage.projection_state import (
    bounded_error_message,
    is_expired,
    iso_after,
    target_matches_namespaces,
)


class MemoryProjectionStateMixin:
    @property
    def _projection_targets(self) -> dict[str, ProjectionTarget]:
        return self.__dict__.setdefault("_projection_targets_state", {})

    @property
    def _projection_checkpoints(self) -> dict[str, ProjectionCheckpoint]:
        return self.__dict__.setdefault("_projection_checkpoints_state", {})

    @property
    def _projection_leases(self) -> dict[str, ProjectionLease]:
        return self.__dict__.setdefault("_projection_leases_state", {})

    @property
    def _projection_attempts(self) -> list[ProjectionAttempt]:
        return self.__dict__.setdefault("_projection_attempts_state", [])

    @property
    def _projection_failures(self) -> dict[tuple[str, str], ProjectionFailure]:
        return self.__dict__.setdefault("_projection_failures_state", {})

    def register_projection_target(self, target: ProjectionTarget) -> str:
        self._projection_targets[target.target_id] = target
        self._projection_checkpoints.setdefault(
            target.target_id, ProjectionCheckpoint(target_id=target.target_id)
        )
        return target.target_id

    def get_projection_target(self, target_id: str) -> ProjectionTarget | None:
        return self._projection_targets.get(target_id)

    def list_projection_targets(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        enabled_only: bool = False,
    ) -> list[ProjectionTarget]:
        targets = [
            target
            for target in self._projection_targets.values()
            if target_matches_namespaces(target, namespaces)
            and (not enabled_only or target.enabled)
        ]
        return sorted(targets, key=lambda item: item.target_id)

    def get_projection_checkpoint(self, target_id: str) -> ProjectionCheckpoint:
        if target_id not in self._projection_targets:
            raise NotFoundError("projection target not found")
        return self._projection_checkpoints.setdefault(
            target_id, ProjectionCheckpoint(target_id=target_id)
        )

    def get_projection_lease(self, target_id: str) -> ProjectionLease | None:
        return self._projection_leases.get(target_id)

    def acquire_projection_lease(
        self, *, target_id: str, owner_id: str, now: str
    ) -> ProjectionLease:
        target = self.get_projection_target(target_id)
        if target is None:
            raise NotFoundError("projection target not found")
        current = self._projection_leases.get(target_id)
        if current is not None and not is_expired(current.expires_at, now):
            if current.owner_id != owner_id:
                raise ProjectionLeaseHeldError("projection target is already leased")
        token = (current.fencing_token if current is not None else 0) + 1
        lease = ProjectionLease(
            target_id=target_id,
            owner_id=owner_id,
            fencing_token=token,
            acquired_at=now,
            expires_at=iso_after(now, target.lease_seconds),
        )
        self._projection_leases[target_id] = lease
        return lease

    def release_projection_lease(
        self, *, target_id: str, owner_id: str, fencing_token: int
    ) -> None:
        lease = self._projection_leases.get(target_id)
        if lease is None:
            return
        if lease.owner_id != owner_id or lease.fencing_token != fencing_token:
            raise ProjectionFenceError("projection lease fencing token rejected")
        del self._projection_leases[target_id]

    def advance_projection_checkpoint(
        self,
        checkpoint: ProjectionCheckpoint,
        *,
        fencing_token: int,
        now: str,
    ) -> None:
        lease = self._projection_leases.get(checkpoint.target_id)
        if lease is None or lease.fencing_token != fencing_token:
            raise ProjectionFenceError("projection lease fencing token rejected")
        if is_expired(lease.expires_at, now):
            raise ProjectionFenceError("projection lease expired")
        current = self.get_projection_checkpoint(checkpoint.target_id)
        if checkpoint.cursor <= current.cursor:
            raise ProjectionCheckpointError("checkpoint cursor must advance")
        self._projection_checkpoints[checkpoint.target_id] = checkpoint

    def record_projection_attempt(self, attempt: ProjectionAttempt) -> None:
        if any(
            item.attempt_id == attempt.attempt_id for item in self._projection_attempts
        ):
            return
        self._projection_attempts.append(attempt)

    def list_projection_attempts(
        self, *, target_id: str, event_id: str | None = None
    ) -> list[ProjectionAttempt]:
        attempts = [
            attempt
            for attempt in self._projection_attempts
            if attempt.target_id == target_id
            and (event_id is None or attempt.event_id == event_id)
        ]
        return sorted(attempts, key=lambda item: (item.cursor, item.attempt_number))

    def put_projection_failure(self, failure: ProjectionFailure) -> None:
        self._projection_failures[(failure.target_id, failure.event_id)] = replace(
            failure, error_message=bounded_error_message(failure.error_message)
        )

    def clear_projection_failure(self, *, target_id: str, event_id: str) -> None:
        self._projection_failures.pop((target_id, event_id), None)

    def release_projection_failure(
        self, *, target_id: str, event_id: str, now: str
    ) -> ProjectionFailure:
        key = (target_id, event_id)
        failure = self._projection_failures.get(key)
        if failure is None:
            raise NotFoundError("projection failure not found")
        released = replace(
            failure,
            retryable=True,
            dead_letter=False,
            next_retry_at=now,
            updated_at=now,
        )
        self._projection_failures[key] = released
        return released

    def list_projection_failures(
        self,
        *,
        target_id: str,
        dead_letter: bool | None = None,
    ) -> list[ProjectionFailure]:
        failures = [
            failure
            for failure in self._projection_failures.values()
            if failure.target_id == target_id
            and (dead_letter is None or failure.dead_letter is dead_letter)
        ]
        return sorted(failures, key=lambda item: (item.cursor, item.event_id))


__all__ = ["MemoryProjectionStateMixin"]
