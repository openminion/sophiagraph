from __future__ import annotations

from sophiagraph import (
    ConsentState,
    EmbeddedQueryPanel,
    MemoryRecord,
    ProfileFieldMapping,
    ProfilePack,
    PrivacyPolicyState,
    PublishProfile,
    RedactionPlan,
    RedactionTarget,
    RelationRollupDefinition,
    SavedViewDefinition,
    SavedViewFilter,
    build_delivery_handoff,
    build_profile_pack_plan,
    build_publish_plan,
    evaluate_live_query_panels,
    evaluate_relation_rollup,
)


def _record(record_id: str, title: str, **meta: object) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope="project:demo",
        type="fact",
        content=title,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        title=title,
        meta=dict(meta),
    )


def test_relation_rollup_counts_explicit_related_records() -> None:
    records = [
        _record(
            "rec-1",
            "Alpha",
            relations=[
                {"relation_type": "supports", "target_record_id": "rec-2"},
                {"relation_type": "blocks", "target_record_id": "rec-3"},
            ],
        ),
        _record("rec-2", "Beta", relations=[]),
    ]

    result = evaluate_relation_rollup(
        RelationRollupDefinition(
            rollup_id="support-count",
            source_view_id="view-1",
            relation_type="supports",
        ),
        records,
    )

    assert result.values == {"rec-1": 1, "rec-2": 0}
    assert result.diagnostics["record_count"] == 2


def test_live_query_panels_reuse_saved_view_filters() -> None:
    records = [
        _record("rec-1", "Alpha", properties={"status": "open"}),
        _record("rec-2", "Beta", properties={"status": "closed"}),
    ]
    panels = (
        EmbeddedQueryPanel(
            panel_id="open-items",
            title="Open items",
            view=SavedViewDefinition(
                view_id="open-view",
                name="Open view",
                filters=SavedViewFilter(
                    field="status",
                    operator="eq",
                    value="open",
                ),
            ),
        ),
    )

    results = evaluate_live_query_panels(panels, records)

    assert len(results) == 1
    assert [row.record_id for row in results[0].result.rows] == ["rec-1"]
    assert "view:open-view" in results[0].explain


def test_publish_plan_shapes_limits_and_delivery_handoff() -> None:
    records = [_record("rec-1", "Alpha"), _record("rec-2", "Beta")]
    plan = build_publish_plan(
        PublishProfile(
            profile_id="share",
            kind="read_only_share",
            max_records=1,
        ),
        records,
    )
    handoff = build_delivery_handoff(
        plan,
        target="static_bundle",
        payload_ref="bundle.json",
    )

    assert plan.included_record_ids == ("rec-1",)
    assert plan.omitted_record_ids == ("rec-2",)
    assert handoff.metadata["record_count"] == 1


def test_publish_plan_applies_privacy_visibility_and_redaction_flags() -> None:
    hidden = _record(
        "hidden",
        "Hidden",
        privacy_policy=PrivacyPolicyState(
            policy_id="hidden-policy",
            consent=ConsentState(status="granted"),
            retrieval_visibility="hidden",
            export_visibility="hidden",
            retention_class="retain",
            erase_intent="none",
            decision_reason="visibility_hidden",
            source_owner="test",
            applied_at="2026-01-01T00:00:00Z",
        ).to_dict(),
    )
    redacted = _record(
        "redacted",
        "Secret",
        privacy_policy=PrivacyPolicyState(
            policy_id="redact-policy",
            consent=ConsentState(status="granted"),
            retrieval_visibility="redacted",
            export_visibility="redacted",
            retention_class="redact_and_retain",
            erase_intent="none",
            decision_reason="redaction_required",
            source_owner="test",
            applied_at="2026-01-01T00:00:00Z",
            redaction_plan=RedactionPlan(
                plan_id="redact-content",
                reason="export_minimization",
                targets=(RedactionTarget(kind="record_content"),),
            ),
        ).to_dict(),
    )

    public = build_publish_plan(
        PublishProfile(profile_id="public", kind="public_export"),
        [hidden, redacted],
    )
    private = build_publish_plan(
        PublishProfile(
            profile_id="private",
            kind="private_snapshot",
            include_private=True,
            include_redacted=True,
        ),
        [hidden, redacted],
    )

    assert public.included_record_ids == ()
    assert public.omitted_record_ids == ("hidden", "redacted")
    assert private.included_record_ids == ("hidden", "redacted")


def test_profile_pack_plan_reports_unknown_lossy_and_required_fields() -> None:
    pack = ProfilePack(
        pack_id="okf-basic",
        target="okf",
        version="2026-06",
        mappings=(
            ProfileFieldMapping(
                source_field="title",
                target_field="title",
                required=True,
            ),
            ProfileFieldMapping(
                source_field="aliases",
                target_field="metadata.aliases",
                lossy=True,
            ),
        ),
    )

    plan = build_profile_pack_plan(
        pack,
        {"aliases": ["Alpha"], "extra": True},
        direction="export",
    )

    assert plan.mapped_fields == {"aliases": "metadata.aliases"}
    assert [diagnostic.kind for diagnostic in plan.diagnostics] == [
        "lossy_field",
        "unknown_field",
        "unknown_field",
    ]
