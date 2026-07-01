"""Typed privacy redaction and export gating example."""

from __future__ import annotations

import json

from sophiagraph.models import (
    ConsentState,
    MemoryNamespace,
    MemoryRecord,
    PrivacyPolicyState,
    RedactionPlan,
    RedactionTarget,
)
from sophiagraph.portability.models import MemoryBundleSnapshot
from sophiagraph.privacy import filter_snapshot_for_export, record_with_privacy_policy


def run_example() -> dict[str, object]:
    namespace = MemoryNamespace(agent_id="example", graph_id="main")
    public = MemoryRecord(
        id="rec-public",
        scope="agent:example",
        type="fact",
        title="Public fact",
        content={"body": "safe to export"},
        created_at="2026-06-30T00:00:00+00:00",
        updated_at="2026-06-30T00:00:00+00:00",
        namespace=namespace,
    )
    private = MemoryRecord(
        id="rec-private",
        scope="agent:example",
        type="fact",
        title="Private fact",
        content={"body": "secret"},
        created_at="2026-06-30T00:00:00+00:00",
        updated_at="2026-06-30T00:00:00+00:00",
        namespace=namespace,
    )
    redacted = record_with_privacy_policy(
        private,
        PrivacyPolicyState(
            policy_id="example-policy",
            consent=ConsentState(status="granted"),
            retrieval_visibility="visible",
            export_visibility="redacted",
            retention_class="retain",
            erase_intent="none",
            decision_reason="redaction_required",
            source_owner="example",
            applied_at="2026-06-30T00:00:00+00:00",
            redaction_plan=RedactionPlan(
                plan_id="example-redaction",
                reason="export_minimization",
                targets=(RedactionTarget(kind="record_content"),),
            ),
        ),
    )
    result = filter_snapshot_for_export(
        MemoryBundleSnapshot(manifest={}, records=[public, redacted]),
        source_owner="example",
    )

    return {
        "exported_record_ids": [record.id for record in result.snapshot.records],
        "redacted_record_ids": [item.record_id for item in result.redactions],
        "omitted_record_ids": [item.record_id for item in result.omitted],
    }


def main() -> int:
    print(json.dumps(run_example(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
