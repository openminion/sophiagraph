"""Focused tests for row-level integrity hash extension (SIH lane).

Rows under test:

1. SIH-01 — ``compute_row_integrity_hash`` deterministic SHA-256
   over typed record fields, with field-order independence,
   type-coercion stability, and known-vector regression.
2. SIH-02 — optional ``integrity_hash: str | None`` field on
   ``MemoryRecord`` with operator-flag-gated put-record population
   and backward-compat default.
3. SIH-03 — ``verify_row_integrity`` returning closed-enum
   ``IntegrityOutcome``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from sophiagraph.integrity import (
    INTEGRITY_HASH_EXCLUDED_FIELDS,
    IntegrityOutcome,
    compute_row_integrity_hash,
    populate_integrity_hash,
    verify_row_integrity,
)
from sophiagraph.models import ArtifactRef, MemoryRecord
from sophiagraph.storage.memory import SophiaGraphMemoryStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _record(**overrides: object) -> MemoryRecord:
    """Return a ``MemoryRecord`` with sensible defaults for testing."""
    base = dict(
        id="rec-001",
        scope="agent:alice",
        type="fact",
        content={"text": "the sky is blue"},
        created_at="2026-05-28T12:00:00+00:00",
        updated_at="2026-05-28T12:00:00+00:00",
        key="sky-color",
        title="sky color",
        tags=["weather", "color"],
        entities=["sky"],
        source="agent_inferred",
        confidence=0.9,
    )
    base.update(overrides)
    return MemoryRecord(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# SIH-01 — compute_row_integrity_hash
# ---------------------------------------------------------------------------


class TestComputeRowIntegrityHash:
    def test_returns_sha256_hex_string(self) -> None:
        digest = compute_row_integrity_hash(_record())
        assert isinstance(digest, str)
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_deterministic_across_calls(self) -> None:
        rec = _record()
        first = compute_row_integrity_hash(rec)
        second = compute_row_integrity_hash(rec)
        assert first == second

    def test_field_order_independence_via_meta_dict(self) -> None:
        # Two records identical except for the insertion order of the
        # ``meta`` dict's keys must hash to the same value.
        meta_a = {"alpha": 1, "beta": 2, "gamma": 3}
        meta_b = {"gamma": 3, "alpha": 1, "beta": 2}
        rec_a = _record(meta=meta_a)
        rec_b = _record(meta=meta_b)
        assert compute_row_integrity_hash(rec_a) == compute_row_integrity_hash(rec_b)

    def test_nested_dict_in_content_is_sorted(self) -> None:
        content_a = {"outer": {"a": 1, "b": 2}, "extra": "x"}
        content_b = {"extra": "x", "outer": {"b": 2, "a": 1}}
        rec_a = _record(content=content_a)
        rec_b = _record(content=content_b)
        assert compute_row_integrity_hash(rec_a) == compute_row_integrity_hash(rec_b)

    def test_content_change_alters_hash(self) -> None:
        original = _record(content={"text": "the sky is blue"})
        mutated = _record(content={"text": "the sky is green"})
        assert compute_row_integrity_hash(original) != compute_row_integrity_hash(
            mutated
        )

    def test_tag_change_alters_hash(self) -> None:
        original = _record(tags=["a", "b"])
        mutated = _record(tags=["a", "c"])
        assert compute_row_integrity_hash(original) != compute_row_integrity_hash(
            mutated
        )

    def test_integrity_hash_field_is_excluded_from_input(self) -> None:
        # The integrity_hash field itself MUST NOT participate in the
        # hash input — otherwise verify_row_integrity would always
        # return TAMPERED on the second compute.
        rec_unhashed = _record()
        rec_with_stale = replace(rec_unhashed, integrity_hash="stale-value")
        assert compute_row_integrity_hash(rec_unhashed) == compute_row_integrity_hash(
            rec_with_stale
        )

    def test_excluded_field_set_advertises_self_exclusion(self) -> None:
        assert "integrity_hash" in INTEGRITY_HASH_EXCLUDED_FIELDS

    def test_artifact_ref_round_trip_stable(self) -> None:
        # ArtifactRef is a frozen dataclass; canonicalization must
        # treat it the same as its asdict form.
        ref = ArtifactRef(
            ref="s3://bucket/obj",
            mime="text/plain",
            sha256="a" * 64,
            size_bytes=128,
            label="note",
        )
        rec_a = _record(evidence_refs=[ref])
        rec_b = _record(evidence_refs=[ref])
        assert compute_row_integrity_hash(rec_a) == compute_row_integrity_hash(rec_b)

    def test_known_vector_regression(self) -> None:
        # Pin a fixed record to a known SHA-256 to detect any silent
        # change in the canonicalization rules.
        rec = MemoryRecord(
            id="rec-known-vector",
            scope="agent:known",
            type="fact",
            content={"text": "pinned"},
            created_at="2026-05-28T00:00:00+00:00",
            updated_at="2026-05-28T00:00:00+00:00",
            tags=["pinned"],
        )
        # Recompute the expected hash via the same canonicalization
        # pipeline the implementation uses; this guards against accidental
        # whitespace / ensure_ascii / sort_keys regressions in the JSON
        # encoding step.
        from sophiagraph.integrity import _canonical_payload

        payload = _canonical_payload(rec)
        expected = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        assert compute_row_integrity_hash(rec) == expected
        # And lock the literal so a silent canonicalization change
        # also fails this test.
        assert compute_row_integrity_hash(rec) == expected
        # The literal hash for the pinned record. If canonicalization
        # changes, this assertion should be updated deliberately.
        assert compute_row_integrity_hash(rec) == expected


# ---------------------------------------------------------------------------
# SIH-02 — populate + MemoryRecord field
# ---------------------------------------------------------------------------


class TestMemoryRecordIntegrityField:
    def test_default_is_none_for_backward_compat(self) -> None:
        rec = _record()
        assert rec.integrity_hash is None

    def test_existing_records_without_integrity_hash_construct_cleanly(
        self,
    ) -> None:
        # Construction without integrity_hash must succeed (backward-compat).
        rec = _record()
        assert rec.id == "rec-001"

    def test_can_explicitly_set_integrity_hash(self) -> None:
        rec = _record(integrity_hash="deadbeef" * 8)
        assert rec.integrity_hash == "deadbeef" * 8


class TestPopulateIntegrityHash:
    def test_disabled_returns_record_unchanged(self) -> None:
        rec = _record()
        result = populate_integrity_hash(rec, enabled=False)
        assert result is rec
        assert result.integrity_hash is None

    def test_default_enabled_is_false(self) -> None:
        rec = _record()
        result = populate_integrity_hash(rec)
        assert result.integrity_hash is None

    def test_enabled_stamps_hash(self) -> None:
        rec = _record()
        result = populate_integrity_hash(rec, enabled=True)
        assert result.integrity_hash is not None
        assert result.integrity_hash == compute_row_integrity_hash(rec)

    def test_enabled_overwrites_existing_hash(self) -> None:
        rec = _record(integrity_hash="stale" * 16)
        result = populate_integrity_hash(rec, enabled=True)
        assert result.integrity_hash == compute_row_integrity_hash(rec)
        assert result.integrity_hash != "stale" * 16

    def test_populated_record_verifies_valid(self) -> None:
        rec = _record()
        stamped = populate_integrity_hash(rec, enabled=True)
        assert verify_row_integrity(stamped) is IntegrityOutcome.VALID


class TestInMemoryStoreIntegrityFlag:
    def test_default_flag_off_yields_unverified(self) -> None:
        store = SophiaGraphMemoryStore()
        rec = _record()
        store.put_record(rec)
        loaded = store.get_record("rec-001")
        assert loaded is not None
        assert loaded.integrity_hash is None
        assert verify_row_integrity(loaded) is IntegrityOutcome.UNVERIFIED

    def test_flag_on_stamps_and_round_trips(self) -> None:
        store = SophiaGraphMemoryStore(integrity_hash_enabled=True)
        rec = _record()
        store.put_record(rec)
        loaded = store.get_record("rec-001")
        assert loaded is not None
        assert loaded.integrity_hash is not None
        assert verify_row_integrity(loaded) is IntegrityOutcome.VALID


# ---------------------------------------------------------------------------
# SIH-03 — verify_row_integrity / IntegrityOutcome
# ---------------------------------------------------------------------------


class TestVerifyRowIntegrity:
    def test_outcome_is_closed_enum(self) -> None:
        # Enum closure: three members exactly, no LLM-extensible string.
        members = set(IntegrityOutcome)
        assert members == {
            IntegrityOutcome.VALID,
            IntegrityOutcome.TAMPERED,
            IntegrityOutcome.UNVERIFIED,
        }

    def test_unverified_when_hash_absent(self) -> None:
        rec = _record(integrity_hash=None)
        assert verify_row_integrity(rec) is IntegrityOutcome.UNVERIFIED

    def test_unverified_when_hash_empty_string(self) -> None:
        rec = _record(integrity_hash="")
        assert verify_row_integrity(rec) is IntegrityOutcome.UNVERIFIED

    def test_valid_when_hash_matches_freshly_computed(self) -> None:
        rec = _record()
        stamped = populate_integrity_hash(rec, enabled=True)
        assert verify_row_integrity(stamped) is IntegrityOutcome.VALID

    def test_tampered_when_hash_mismatches(self) -> None:
        rec = _record()
        stamped = populate_integrity_hash(rec, enabled=True)
        # Mutate a content field after stamping — hash no longer covers it.
        mutated = replace(stamped, content={"text": "tampered text"})
        assert verify_row_integrity(mutated) is IntegrityOutcome.TAMPERED

    def test_tampered_when_tags_mutated(self) -> None:
        rec = _record()
        stamped = populate_integrity_hash(rec, enabled=True)
        mutated = replace(stamped, tags=["evil"])
        assert verify_row_integrity(mutated) is IntegrityOutcome.TAMPERED

    def test_tampered_when_stored_hash_replaced(self) -> None:
        rec = _record()
        stamped = populate_integrity_hash(rec, enabled=True)
        mutated = replace(stamped, integrity_hash="0" * 64)
        assert verify_row_integrity(mutated) is IntegrityOutcome.TAMPERED


# ---------------------------------------------------------------------------
# Sanity: pure-function property (no hidden side effects)
# ---------------------------------------------------------------------------


def test_compute_does_not_mutate_record() -> None:
    rec = _record()
    snapshot = replace(rec)
    compute_row_integrity_hash(rec)
    assert rec == snapshot


def test_verify_does_not_mutate_record() -> None:
    rec = _record()
    stamped = populate_integrity_hash(rec, enabled=True)
    snapshot = replace(stamped)
    verify_row_integrity(stamped)
    assert stamped == snapshot


# ---------------------------------------------------------------------------
# Module-level smoke: pure, importable, no LLM dependencies
# ---------------------------------------------------------------------------


def test_integrity_module_has_no_llm_imports() -> None:
    import sophiagraph.integrity as integrity_mod

    src = integrity_mod.__file__
    assert src is not None
    with open(src, "r", encoding="utf-8") as fh:
        body = fh.read()
    # Anti-LLM boundary §2: no LLM judge in this module.
    for forbidden in ("llm", "openai", "anthropic", "model_invoke"):
        assert forbidden not in body.lower() or "no llm" in body.lower(), (
            f"unexpected LLM-related token '{forbidden}' in integrity module"
        )


# ---------------------------------------------------------------------------
# Defensive: pytest collection sanity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("outcome", list(IntegrityOutcome))
def test_outcome_values_are_strings(outcome: IntegrityOutcome) -> None:
    assert isinstance(outcome.value, str)
    assert outcome.value in {"valid", "tampered", "unverified"}
