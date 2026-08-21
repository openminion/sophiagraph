"""GraphFakos adapter for Sophiagraph durable memory previews."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from graphfakos import (
    GraphFakosActionStatus,
    GraphFakosCitation,
    GraphFakosEdge,
    GraphFakosGraph,
    GraphFakosGraphAction,
    GraphFakosKnowledgeCapture,
    GraphFakosNode,
    GraphFakosProvenance,
    GraphFakosProvider,
    GraphFakosRequest,
)

from sophiagraph.query import CandidateListOptions, LinkQueryOptions, ListQueryOptions
from sophiagraph.storage.base import SophiaGraphStore
from sophiagraph.workbench import WorkbenchActionKind, WorkbenchActionRequest
from sophiagraph.workbench_actions import execute_workbench_action
from sophiagraph.models import (
    ArtifactRef,
    CandidateReview,
    KnowledgeDocumentBlock,
    MemoryCandidate,
    MemoryNamespace,
    MemoryRecord,
    StructuralLink,
    WorkbenchActionExecutionContext,
    WorkbenchActionResult,
)

_BASE_CAPABILITIES = (
    "search",
    "neighborhood",
    "path",
    "provenance",
    "timeline",
    "provider_status",
    "context_preview",
    "durable_memory",
    "static_export",
    "local_preview",
)
_ACTION_CAPABILITIES = ("knowledge_capture", "graph_actions")


class SophiagraphViewerProvider(GraphFakosProvider):
    provider_id = "sophiagraph"
    provider_label = "Sophiagraph"
    graph_role = "memory"
    capabilities = _BASE_CAPABILITIES

    def __init__(
        self,
        *,
        store: SophiaGraphStore,
        scope: str,
        namespace: MemoryNamespace,
        principal_id: str = "",
        workspace_id: str = "workspace:local",
        workspace_root: str = "",
        source_root: str = "",
    ) -> None:
        self._store = store
        self._scope = scope
        self._namespace = namespace
        self._principal_id = principal_id
        self._workspace_id = workspace_id
        self._workspace_root = workspace_root
        self._source_root = source_root
        self.capabilities = (
            (*_BASE_CAPABILITIES, *_ACTION_CAPABILITIES)
            if principal_id
            else _BASE_CAPABILITIES
        )

    def load_graph(self, request: GraphFakosRequest) -> GraphFakosGraph:
        records = tuple(
            self._store.list_records(
                ListQueryOptions(scopes=[self._scope], namespaces=[self._namespace])
            )
        )
        links = _record_links(self._store, records, self._namespace)
        candidates = tuple(
            candidate
            for candidate in self._store.list_candidates(
                CandidateListOptions(status=None, limit=max(request.limit, 25))
            )
            if _candidate_in_scope(candidate, self._scope, self._namespace)
        )
        blocks = {
            block.record_id: block
            for record in records
            for block in self._store.list_document_blocks(record_id=record.id)
        }
        provenance = tuple(_record_provenance(record) for record in records)
        citations = tuple(
            GraphFakosCitation(
                id=f"citation:{block.block_id}",
                label=block.anchor or block.block_id,
                path=block.document_id,
                excerpt=block.excerpt,
                provider_payload={"record_id": block.record_id},
            )
            for block in blocks.values()
        )
        nodes = tuple(
            _record_node(record, blocks.get(record.id)) for record in records
        ) + tuple(_candidate_node(candidate) for candidate in candidates)
        edges = tuple(_link_edge(link) for link in links) + tuple(
            _candidate_edge(candidate, records) for candidate in candidates
        )
        edges = tuple(edge for edge in edges if edge is not None)
        return GraphFakosGraph(
            graph_id=_graph_id(self._namespace),
            label="Sophiagraph Durable Memory",
            provider_id=self.provider_id,
            provider_label=self.provider_label,
            graph_role=self.graph_role,
            capabilities=self.capabilities,
            nodes=nodes,
            edges=edges,
            provenance=provenance,
            citations=citations,
            stats={
                "scope": self._scope,
                "records": len(records),
                "candidates": len(candidates),
                "links": len(links),
            },
            generated_at="2026-06-22T00:00:00+00:00",
            provider_payload={
                "integration_summary": (
                    "Inspect Sophiagraph durable-memory records, candidates, "
                    "trust fields, provenance, citations, and local workbench "
                    "actions through the shared GraphFakos viewer."
                ),
                "integration_commands": (
                    "sophiagraph-ui --workspace <workspace-root> --screen explore --serve --open",
                    "python -m sophiagraph ui-preview --screen views --serve",
                ),
                "inspector_schemas": _inspector_schemas(),
            },
        )

    def capture_knowledge(
        self,
        capture: GraphFakosKnowledgeCapture,
    ) -> dict[str, object]:
        if not self._actions_enabled:
            status = GraphFakosActionStatus(
                action_id=f"capture:{capture.link_node_id or 'graph'}",
                status="unsupported",
                message="Sophiagraph capture requires a live action-enabled preview",
            )
            return {
                "ok": False,
                "status": status.to_dict(),
                "capture": capture.to_dict(),
            }
        note_key = str(
            capture.provider_payload.get("note_key")
            or capture.link_node_id
            or f"capture-{capture.kind}"
        )
        title = str(capture.provider_payload.get("title") or note_key)
        action_id = str(
            capture.provider_payload.get("action_id") or f"capture:{note_key}"
        )
        result = execute_workbench_action(
            self._store,
            WorkbenchActionRequest(
                action="save_note",
                target_id=note_key,
                actor_id=self._principal_id,
                workspace_id=self._workspace_id,
                payload_kind="note",
                payload={
                    "note_key": note_key,
                    "title": title,
                    "body": capture.text,
                    "tags": list(capture.tags),
                    "relative_path": capture.provider_payload.get("relative_path"),
                    "expected_content_sha256": capture.provider_payload.get(
                        "expected_content_sha256"
                    ),
                },
            ),
            self._context(action_id=action_id),
        )
        status = _graphfakos_status(result, graph_id=_graph_id(self._namespace))
        return {
            "ok": result.outcome == "applied",
            "status": status.to_dict(),
            "capture": capture.to_dict(),
            "result": result.to_dict(),
        }

    def submit_graph_action(
        self,
        action: GraphFakosGraphAction,
    ) -> GraphFakosActionStatus:
        if not self._actions_enabled:
            return GraphFakosActionStatus(
                action_id=action.action_id,
                status="unsupported",
                message="Sophiagraph actions require a live action-enabled preview",
                graph_id=_graph_id(self._namespace),
            )
        if action.action_type not in {
            "approve_candidate",
            "reject_candidate",
            "promote_candidate",
            "apply_repair",
            "restore_workspace",
            "build_publish_plan",
            "open_graph_selection",
            "propose_note_edit",
            "approve_workspace_edit",
            "reject_workspace_edit",
            "save_note",
        }:
            return GraphFakosActionStatus(
                action_id=action.action_id,
                status="unsupported",
                message=f"unsupported Sophiagraph action: {action.action_type}",
                graph_id=_graph_id(self._namespace),
                provider_payload={"reason_code": "unsupported_action"},
            )
        target_id = action.target_id or action.target_node_id or action.source_id
        result = execute_workbench_action(
            self._store,
            WorkbenchActionRequest(
                action=cast(WorkbenchActionKind, action.action_type),
                target_id=target_id,
                actor_id=self._principal_id,
                workspace_id=self._workspace_id,
                payload_kind="graph_action",
                payload={
                    **dict(action.provider_payload),
                    "label": action.label,
                    "body": action.body,
                    "tags": list(action.tags),
                },
            ),
            self._context(action_id=action.action_id),
        )
        return _graphfakos_status(result, graph_id=_graph_id(self._namespace))

    @property
    def _actions_enabled(self) -> bool:
        return bool(self._principal_id)

    def _context(self, *, action_id: str) -> WorkbenchActionExecutionContext:
        return WorkbenchActionExecutionContext(
            action_id=action_id,
            request_id=action_id,
            principal_id=self._principal_id,
            workspace_id=self._workspace_id,
            scope=self._scope,
            namespace=self._namespace,
            workspace_root=self._workspace_root,
            source_root=self._source_root,
        )


def _graph_id(namespace: MemoryNamespace) -> str:
    graph_id = namespace.graph_id
    agent_id = namespace.agent_id
    return ":".join(part for part in (agent_id, graph_id) if part) or "sophiagraph"


def _record_node(
    record: MemoryRecord,
    block: KnowledgeDocumentBlock | None,
) -> GraphFakosNode:
    title = record.title or record.id
    text = _memory_summary(record.content)
    tags = (
        "record",
        record.type,
        record.tier,
    )
    citation_ids = (f"citation:{block.block_id}",) if block else ()
    return GraphFakosNode(
        id=record.id,
        label=str(title),
        kind="memory_record",
        summary=text,
        tags=tags,
        confidence=record.confidence,
        source=record.source or str(record.meta.get("document", "")),
        timestamps={
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        },
        provenance_ids=(f"provenance:{record.id}",),
        citation_ids=citation_ids,
        provider_payload={
            "record_id": record.id,
            "key": record.key,
            "scope": record.scope,
            "namespace": record.effective_namespace.as_dict(),
            "memory_type": record.type,
            "tier": record.tier,
            "source": record.source,
            "visibility": record.visibility,
            "confidence": record.confidence,
            "access_count": record.access_count,
            "is_deleted": record.is_deleted,
            "supersedes_id": record.supersedes_id,
            "superseded_by_id": record.superseded_by_id,
            "valid_to": record.valid_to,
            "evidence_refs": _artifact_refs(record.evidence_refs),
        },
    )


def _record_links(
    store: SophiaGraphStore,
    records: tuple[MemoryRecord, ...],
    namespace: MemoryNamespace,
) -> tuple[StructuralLink, ...]:
    links_by_id: dict[str, StructuralLink] = {}
    for record in records:
        for link in store.list_links(
            LinkQueryOptions(
                record_id=record.id,
                direction="both",
                namespaces=[namespace],
            )
        ):
            links_by_id[link.link_id] = link
    return tuple(links_by_id.values())


def _candidate_node(candidate: MemoryCandidate) -> GraphFakosNode:
    title = candidate.title or candidate.candidate_id
    text = _memory_summary(candidate.content)
    return GraphFakosNode(
        id=f"candidate:{candidate.candidate_id}",
        label=str(title),
        kind="memory_candidate",
        summary=text,
        tags=(
            "candidate",
            candidate.status,
            candidate.type,
        ),
        confidence=candidate.confidence,
        source=candidate.source,
        timestamps={
            "created_at": str(candidate.created_at or ""),
            "updated_at": str(candidate.updated_at or ""),
        },
        provider_payload={
            "candidate_id": candidate.candidate_id,
            "status": candidate.status,
            "session_id": candidate.session_id,
            "memory_type": candidate.type,
            "namespace": _candidate_namespace(candidate).as_dict(),
            "claim_key": candidate.claim_key,
            "polarity": candidate.polarity,
            "source_class": candidate.source_class,
            "proposed_scope": candidate.proposed_scope,
            "evidence_refs": _artifact_refs(candidate.evidence_refs),
            "reviewed_by": _reviewer(candidate.review),
        },
    )


def _candidate_in_scope(
    candidate: MemoryCandidate,
    scope: str,
    namespace: MemoryNamespace,
) -> bool:
    return (
        candidate.proposed_scope == scope
        and _candidate_namespace(candidate) == namespace
    )


def _record_provenance(record: MemoryRecord) -> GraphFakosProvenance:
    return GraphFakosProvenance(
        id=f"provenance:{record.id}",
        provider_id="sophiagraph",
        source_type="durable_memory",
        source_label=record.source or "sophiagraph",
        excerpt=str(record.title or record.id),
        created_at=record.created_at,
        updated_at=record.updated_at,
        confidence=record.confidence,
    )


def _candidate_namespace(candidate: MemoryCandidate) -> MemoryNamespace:
    return candidate.namespace or MemoryNamespace.from_scope(candidate.proposed_scope)


def _memory_summary(content: dict[str, Any] | str) -> str:
    if isinstance(content, dict):
        return str(content.get("text", content))
    return content


def _artifact_refs(refs: Sequence[ArtifactRef]) -> tuple[str, ...]:
    return tuple(ref.ref for ref in refs)


def _reviewer(review: CandidateReview | None) -> str:
    return review.reviewer if review else ""


def _payload_field(key: str, label: str) -> dict[str, str]:
    return {"key": key, "label": label, "source": "provider_payload"}


def _inspector_schemas() -> tuple[dict[str, object], ...]:
    return (
        {
            "schema_id": "sophiagraph-memory-record",
            "node_kind": "memory_record",
            "fields": (
                _payload_field("record_id", "Record id"),
                _payload_field("scope", "Scope"),
                _payload_field("memory_type", "Type"),
                _payload_field("tier", "Tier"),
                _payload_field("confidence", "Confidence"),
                _payload_field("source", "Source"),
                _payload_field("evidence_refs", "Evidence"),
            ),
        },
        {
            "schema_id": "sophiagraph-memory-candidate",
            "node_kind": "memory_candidate",
            "fields": (
                _payload_field("candidate_id", "Candidate id"),
                _payload_field("status", "Status"),
                _payload_field("claim_key", "Claim key"),
                _payload_field("polarity", "Polarity"),
                _payload_field("source_class", "Source class"),
                _payload_field("evidence_refs", "Evidence"),
            ),
        },
    )


def _link_edge(link: StructuralLink) -> GraphFakosEdge:
    label = link.relation_type or link.link_kind
    return GraphFakosEdge(
        id=link.link_id,
        source_id=link.source_record_id,
        target_id=link.target_record_id,
        kind=label,
        label=label,
        confidence=1.0,
    )


def _candidate_edge(
    candidate: MemoryCandidate,
    records: tuple[MemoryRecord, ...],
) -> GraphFakosEdge | None:
    if not records:
        return None
    return GraphFakosEdge(
        id=f"edge:candidate:{candidate.candidate_id}",
        source_id=f"candidate:{candidate.candidate_id}",
        target_id=records[0].id,
        kind="promote_candidate",
        label="promote candidate",
        confidence=candidate.confidence,
    )


def _graphfakos_status(
    result: WorkbenchActionResult,
    *,
    graph_id: str,
) -> GraphFakosActionStatus:
    return GraphFakosActionStatus(
        action_id=result.action_id,
        status=result.outcome,
        message=result.message,
        graph_id=graph_id,
        provider_payload={
            "reason_code": result.reason_code,
            "audit_refs": list(result.audit_refs),
            "audit_durability": result.audit_durability,
            "affected_refs": list(result.affected_refs),
            "result": result.to_dict(),
        },
    )


__all__ = [
    "SophiagraphViewerProvider",
]
