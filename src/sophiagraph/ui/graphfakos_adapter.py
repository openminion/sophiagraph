"""GraphFakos adapter for Sophiagraph durable memory previews."""

from __future__ import annotations

from typing import cast

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
from sophiagraph.workbench import WorkbenchActionKind, WorkbenchActionRequest
from sophiagraph.workbench_actions import execute_workbench_action
from sophiagraph.models import (
    MemoryNamespace,
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
        store: object,
        scope: str,
        namespace: object,
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
                "integration_commands": (
                    "sophiagraph-ui --workspace <workspace-root> --screen explore --serve --open",
                    "python -m sophiagraph ui-preview --screen views --serve",
                )
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
        namespace = (
            self._namespace
            if isinstance(self._namespace, MemoryNamespace)
            else MemoryNamespace.from_scope(self._scope)
        )
        return WorkbenchActionExecutionContext(
            action_id=action_id,
            request_id=action_id,
            principal_id=self._principal_id,
            workspace_id=self._workspace_id,
            scope=self._scope,
            namespace=namespace,
            workspace_root=self._workspace_root,
            source_root=self._source_root,
        )


def _graph_id(namespace: object) -> str:
    graph_id = getattr(namespace, "graph_id", None)
    agent_id = getattr(namespace, "agent_id", None)
    return ":".join(part for part in (agent_id, graph_id) if part) or "sophiagraph"


def _record_node(record: object, block: object | None) -> GraphFakosNode:
    meta = getattr(record, "meta", {}) or {}
    title = getattr(record, "title", None) or getattr(record, "id")
    content = getattr(record, "content", {}) or {}
    text = (
        content.get("text", str(content)) if isinstance(content, dict) else str(content)
    )
    tags = (
        "record",
        str(getattr(record, "type", "memory")),
        str(getattr(record, "tier", "stored")),
    )
    citation_ids = (f"citation:{block.block_id}",) if block else ()
    return GraphFakosNode(
        id=str(getattr(record, "id")),
        label=str(title),
        kind="memory_record",
        summary=text,
        tags=tags,
        confidence=getattr(record, "confidence", None),
        source=str(getattr(record, "source", "") or meta.get("document", "")),
        timestamps={
            "created_at": str(getattr(record, "created_at", "")),
            "updated_at": str(getattr(record, "updated_at", "")),
        },
        provenance_ids=(f"provenance:{getattr(record, 'id')}",),
        citation_ids=citation_ids,
        provider_payload={
            "key": getattr(record, "key", None),
            "scope": getattr(record, "scope", None),
            "claim_key": getattr(record, "claim_key", None),
            "source_class": getattr(record, "source_class", None),
            "polarity": getattr(record, "polarity", None),
        },
    )


def _record_links(
    store: object,
    records: tuple[object, ...],
    namespace: object,
) -> tuple[object, ...]:
    links_by_id: dict[str, object] = {}
    for record in records:
        for link in store.list_links(
            LinkQueryOptions(
                record_id=str(getattr(record, "id")),
                direction="both",
                namespaces=[namespace],
            )
        ):
            links_by_id[str(getattr(link, "link_id"))] = link
    return tuple(links_by_id.values())


def _candidate_node(candidate: object) -> GraphFakosNode:
    title = getattr(candidate, "title", None) or getattr(candidate, "candidate_id")
    content = getattr(candidate, "content", {}) or {}
    text = (
        content.get("text", str(content)) if isinstance(content, dict) else str(content)
    )
    return GraphFakosNode(
        id=f"candidate:{getattr(candidate, 'candidate_id')}",
        label=str(title),
        kind="memory_candidate",
        summary=text,
        tags=(
            "candidate",
            str(getattr(candidate, "status", "")),
            str(getattr(candidate, "type", "")),
        ),
        confidence=getattr(candidate, "confidence", None),
        source=str(getattr(candidate, "source", "")),
        timestamps={
            "created_at": str(getattr(candidate, "created_at", "")),
            "updated_at": str(getattr(candidate, "updated_at", "")),
        },
        provider_payload={
            "claim_key": getattr(candidate, "claim_key", None),
            "polarity": getattr(candidate, "polarity", None),
            "source_class": getattr(candidate, "source_class", None),
            "proposed_scope": getattr(candidate, "proposed_scope", None),
        },
    )


def _candidate_in_scope(candidate: object, scope: str, namespace: object) -> bool:
    candidate_namespace = getattr(candidate, "namespace", None)
    if candidate_namespace is None:
        candidate_namespace = MemoryNamespace.from_scope(
            str(getattr(candidate, "proposed_scope", ""))
        )
    return (
        str(getattr(candidate, "proposed_scope", "")) == scope
        and candidate_namespace == namespace
    )


def _record_provenance(record: object) -> GraphFakosProvenance:
    record_id = getattr(record, "id")
    source = str(getattr(record, "source", "") or "sophiagraph")
    return GraphFakosProvenance(
        id=f"provenance:{record_id}",
        provider_id="sophiagraph",
        source_type="durable_memory",
        source_label=source,
        excerpt=str(getattr(record, "title", None) or record_id),
        created_at=str(getattr(record, "created_at", "")),
        updated_at=str(getattr(record, "updated_at", "")),
        confidence=getattr(record, "confidence", None),
    )


def _link_edge(link: object) -> GraphFakosEdge:
    return GraphFakosEdge(
        id=str(getattr(link, "link_id")),
        source_id=str(getattr(link, "source_record_id")),
        target_id=str(getattr(link, "target_record_id")),
        kind=str(
            getattr(link, "relation_type", None) or getattr(link, "link_kind", "")
        ),
        label=str(
            getattr(link, "relation_type", None) or getattr(link, "link_kind", "")
        ),
        confidence=1.0,
    )


def _candidate_edge(
    candidate: object,
    records: tuple[object, ...],
) -> GraphFakosEdge | None:
    if not records:
        return None
    return GraphFakosEdge(
        id=f"edge:candidate:{getattr(candidate, 'candidate_id')}",
        source_id=f"candidate:{getattr(candidate, 'candidate_id')}",
        target_id=str(getattr(records[0], "id")),
        kind="promote_candidate",
        label="promote candidate",
        confidence=getattr(candidate, "confidence", None),
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
