"""Durable-knowledge package errors."""

from __future__ import annotations

from typing import Any, ClassVar


class MemctlError(RuntimeError):
    """Base error carrying a stable code and optional details."""

    code: ClassVar[str] = "UNKNOWN"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class InvalidArgumentError(MemctlError):
    code = "INVALID_ARGUMENT"


class NotFoundError(MemctlError):
    code = "NOT_FOUND"


class ConstraintViolationError(MemctlError):
    code = "CONSTRAINT_VIOLATION"


class PromotionDeniedError(MemctlError):
    code = "PROMOTION_DENIED"


class StoreReadError(MemctlError):
    code = "STORE_READ_FAILED"


class StoreWriteError(MemctlError):
    code = "STORE_WRITE_FAILED"


class MigrationRequiredError(MemctlError):
    code = "MIGRATION_REQUIRED"


class MemoryBlockClassNotEligibleError(MemctlError):
    """Block creation rejected because the class is not on the allowlist."""

    code = "MEMORY_BLOCK_CLASS_NOT_ELIGIBLE"


class MemoryBlockModeNotYetSupportedError(MemctlError):
    """Block creation rejected because the mode is schema-valid but deferred."""

    code = "MEMORY_BLOCK_MODE_NOT_YET_SUPPORTED"


class MemoryBlockModeInvalidError(MemctlError):
    """Block construction rejected because the mode is not a known literal."""

    code = "MEMORY_BLOCK_MODE_INVALID"


class MemoryBlocksBudgetHardFloorViolatedError(MemctlError):
    """Block context assembly failed because the identity floor cannot fit."""

    code = "MEMORY_BLOCKS_BUDGET_HARD_FLOOR_VIOLATED"


class MemoryBlockEditDeniedError(MemctlError):
    """Block update/delete rejected by the edit-semantics gate."""

    code = "MEMORY_BLOCK_EDIT_DENIED"


# Audit-event codes that do not all correspond to raised exceptions.
MEMORY_BLOCKS_BUDGET_EXCEEDED = "MEMORY_BLOCKS_BUDGET_EXCEEDED"
MEMORY_BLOCK_STALE_SURFACED = "MEMORY_BLOCK_STALE_SURFACED"
MEMORY_BLOCK_EDIT_DENIED = "MEMORY_BLOCK_EDIT_DENIED"
MEMORY_BLOCK_DISAGREEMENT_RECORDED = "MEMORY_BLOCK_DISAGREEMENT_RECORDED"

MEMORY_IDENTITY_BLOCK_HARD_FLOOR_TOKENS = 128
MEMORY_BLOCKS_BUDGET_CEILING_DEFAULT_TOKENS = 4096
