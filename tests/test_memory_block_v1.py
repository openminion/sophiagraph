"""MemoryBlock v1 DTO, class, mode, and error-code tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from sophiagraph.contracts.errors import (
    InvalidArgumentError,
    MEMORY_BLOCK_STALE_SURFACED,
    MEMORY_BLOCKS_BUDGET_EXCEEDED,
    MemoryBlockClassNotEligibleError,
    MemoryBlockModeInvalidError,
    MemoryBlockModeNotYetSupportedError,
    MemoryBlocksBudgetHardFloorViolatedError,
)
from sophiagraph.models import (
    MEMORY_BLOCK_DEFERRED_MODES,
    MEMORY_BLOCK_V1_CLASS_ALLOWLIST,
    MEMORY_BLOCK_V1_MODES,
    MemoryBlock,
    MemoryNamespace,
    validate_block_for_creation,
)


def _block(**overrides):
    """Construct a default-valid MemoryBlock with field overrides."""

    payload = {
        "block_id": "blk-1",
        "class_name": "agent_identity",
        "mode": "read_only",
        "content": "I am a helpful assistant.",
        "token_estimate": 12,
        "owner_namespace": MemoryNamespace(agent_id="agent-a"),
        "source": "agent_config",
        "provenance": {},
        "created_at": "2026-05-26T00:00:00+00:00",
        "last_updated_at": "2026-05-26T00:00:00+00:00",
        "last_updated_by": "system",
        "stale_after": None,
    }
    payload.update(overrides)
    return MemoryBlock(**payload)


# Exit criterion (a): v1 class allowlist enforcement.


class TestClassAllowlist:
    @pytest.mark.parametrize(
        "class_name", ["agent_identity", "active_mission", "session_pin"]
    )
    def test_eligible_v1_classes_pass(self, class_name: str) -> None:
        block = _block(class_name=class_name)
        # Must not raise.
        validate_block_for_creation(block)

    def test_allowlist_constant_matches_frozen_v1_decision(self) -> None:
        assert MEMORY_BLOCK_V1_CLASS_ALLOWLIST == frozenset(
            {"agent_identity", "active_mission", "session_pin"}
        )


# Exit criterion (b): deferred modes round-trip through DTO but fail creation.


class TestDeferredModeRoundTripVsCreation:
    @pytest.mark.parametrize("deferred_mode", ["shared", "writable"])
    def test_dto_constructor_accepts_deferred_modes(self, deferred_mode: str) -> None:
        """A bundle reader must be able to hydrate v2 blocks without crashing."""

        block = _block(mode=deferred_mode)
        assert block.mode == deferred_mode

    @pytest.mark.parametrize("deferred_mode", ["shared", "writable"])
    def test_creation_validator_rejects_deferred_modes(
        self, deferred_mode: str
    ) -> None:
        block = _block(mode=deferred_mode)
        with pytest.raises(MemoryBlockModeNotYetSupportedError) as excinfo:
            validate_block_for_creation(block)
        assert excinfo.value.code == "MEMORY_BLOCK_MODE_NOT_YET_SUPPORTED"
        assert excinfo.value.details["mode"] == deferred_mode
        # Active modes are surfaced so operators see what IS supported.
        assert set(excinfo.value.details["active"]) == MEMORY_BLOCK_V1_MODES

    def test_deferred_constant_matches_frozen_v1_decision(self) -> None:
        assert MEMORY_BLOCK_DEFERRED_MODES == frozenset({"shared", "writable"})

    def test_v1_active_modes_constant_matches_frozen_decision(self) -> None:
        assert MEMORY_BLOCK_V1_MODES == frozenset({"read_only", "pinned"})


# Exit criterion (c): unknown modes fail with MEMORY_BLOCK_MODE_INVALID.


class TestUnknownModeRejection:
    @pytest.mark.parametrize("bad_mode", ["", "foo", "READ_ONLY", "Pinned"])
    def test_dto_constructor_rejects_unknown_mode(self, bad_mode: str) -> None:
        """The DTO rejects modes outside the known literal set."""

        if bad_mode == "":
            # Empty string fails the structural check before the mode
            # literal check; that's still the right rejection class for
            # the malformed-bundle case.
            with pytest.raises(InvalidArgumentError):
                _block(mode=bad_mode)
            return
        with pytest.raises(MemoryBlockModeInvalidError) as excinfo:
            _block(mode=bad_mode)
        assert excinfo.value.code == "MEMORY_BLOCK_MODE_INVALID"
        assert excinfo.value.details["mode"] == bad_mode


# Exit criterion (d): unknown classes fail with MEMORY_BLOCK_CLASS_NOT_ELIGIBLE.


class TestClassNotEligibleRejection:
    @pytest.mark.parametrize(
        "bad_class",
        [
            "project_config",  # rejected for v1 per the eligibility matrix
            "hot_procedural",  # deferred to v2
            "user_facts",  # deferred to v2
            "room_shared_context",  # deferred to v2
            "arbitrary_invented_class",  # default-deny catches this
        ],
    )
    def test_creation_validator_rejects_non_eligible_classes(
        self, bad_class: str
    ) -> None:
        block = _block(class_name=bad_class)
        with pytest.raises(MemoryBlockClassNotEligibleError) as excinfo:
            validate_block_for_creation(block)
        assert excinfo.value.code == "MEMORY_BLOCK_CLASS_NOT_ELIGIBLE"
        assert excinfo.value.details["class_name"] == bad_class
        assert set(excinfo.value.details["eligible"]) == MEMORY_BLOCK_V1_CLASS_ALLOWLIST

    def test_dto_constructor_does_not_validate_class_eligibility(self) -> None:
        """The class-eligibility check is creation-only."""

        block = _block(class_name="hot_procedural")
        assert block.class_name == "hot_procedural"


# Exit criterion (e): no parallel namespace alias.


class TestNamespaceOwnerGrounding:
    def test_owner_namespace_must_be_memory_namespace_instance(self) -> None:
        """The DTO rejects a parallel namespace alias / wrong type."""

        # A bare dict is the most common "I'll just make my own namespace"
        # mistake; the DTO must reject it loudly.
        with pytest.raises(InvalidArgumentError):
            _block(owner_namespace={"agent_id": "agent-a"})  # type: ignore[arg-type]

    def test_owner_namespace_carries_canonical_typed_owner(self) -> None:
        ns = MemoryNamespace(agent_id="agent-a", session_id="s-1")
        block = _block(owner_namespace=ns)
        assert block.owner_namespace is ns
        # Round-trip through the typed namespace API still works.
        assert block.owner_namespace.agent_id == "agent-a"
        assert block.owner_namespace.session_id == "s-1"

    def test_no_floating_namespace_alias_exported_from_models(self) -> None:
        """The models surface should not expose a parallel namespace alias."""

        from sophiagraph import models

        assert not hasattr(models, "NamespaceRef")
        assert not hasattr(models, "BlockNamespaceRef")


class TestTypedCodeOwnership:
    def test_all_six_codes_are_centrally_owned(self) -> None:
        """Error and audit codes should stay centralized and reusable."""

        # Error classes
        assert (
            MemoryBlockClassNotEligibleError.code == "MEMORY_BLOCK_CLASS_NOT_ELIGIBLE"
        )
        assert (
            MemoryBlockModeNotYetSupportedError.code
            == "MEMORY_BLOCK_MODE_NOT_YET_SUPPORTED"
        )
        assert MemoryBlockModeInvalidError.code == "MEMORY_BLOCK_MODE_INVALID"
        assert (
            MemoryBlocksBudgetHardFloorViolatedError.code
            == "MEMORY_BLOCKS_BUDGET_HARD_FLOOR_VIOLATED"
        )
        # Audit-event constants (no raised exception, just structured event codes)
        assert MEMORY_BLOCKS_BUDGET_EXCEEDED == "MEMORY_BLOCKS_BUDGET_EXCEEDED"
        assert MEMORY_BLOCK_STALE_SURFACED == "MEMORY_BLOCK_STALE_SURFACED"


# DTO structural validation (defense-in-depth coverage).


class TestDtoStructuralValidation:
    def test_missing_block_id_rejected(self) -> None:
        with pytest.raises(InvalidArgumentError):
            _block(block_id="")

    def test_missing_class_name_rejected(self) -> None:
        with pytest.raises(InvalidArgumentError):
            _block(class_name="")

    def test_negative_token_estimate_rejected(self) -> None:
        with pytest.raises(InvalidArgumentError):
            _block(token_estimate=-1)

    def test_non_string_content_rejected(self) -> None:
        with pytest.raises(InvalidArgumentError):
            _block(content=123)  # type: ignore[arg-type]

    def test_non_mapping_provenance_rejected(self) -> None:
        with pytest.raises(InvalidArgumentError):
            _block(provenance="not-a-mapping")  # type: ignore[arg-type]

    def test_block_is_frozen_dataclass(self) -> None:
        block = _block()
        with pytest.raises(FrozenInstanceError):
            block.content = "mutated"  # type: ignore[misc]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
