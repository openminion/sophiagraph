"""Authorized gateway over trusted Sophiagraph stores."""

from __future__ import annotations

from dataclasses import replace
from time import perf_counter
from typing import Any

from sophiagraph.access.contracts import (
    DelegationMemoryGrant,
    DelegationMemoryGrantResolver,
    MemoryAccessContext,
    MemoryAccessDecision,
    MemoryAccessRequest,
)
from sophiagraph.access.policy import evaluate_memory_access
from sophiagraph.access.telemetry import (
    MemoryAccessTelemetryEvent,
    MemoryAccessTelemetryRecorder,
    noop_access_telemetry_recorder,
)
from sophiagraph.audit.events import (
    MemoryAuditEvent,
    MemoryAuditRecorder,
    noop_audit_recorder,
)
from sophiagraph.candidate_review import (
    CandidateReviewDecision,
    apply_candidate_promotion_plan,
    apply_candidate_review,
    build_candidate_promotion_plan,
)
from sophiagraph.federation import (
    FederatedWorkspaceQuery,
    FederatedWorkspaceResult,
    run_federated_workspace_query,
)
from sophiagraph.models import MemoryCandidate, MemoryNamespace, MemoryRecord
from sophiagraph.portability import (
    MemoryBundleExportOptions,
    MemoryBundleImportOptions,
    MemoryBundleSnapshot,
)
from sophiagraph.query import (
    CandidateListOptions,
    GraphSnapshot,
    LinkQueryOptions,
    ListQueryOptions,
    LocalGraphOptions,
    SearchQueryOptions,
)
from sophiagraph.storage import SophiaGraphStore
from sophiagraph.storage.graph_helpers import namespace_matches_filters


class DelegatedMemoryAccessDeniedError(PermissionError):
    """Raised when a mutation or bulk operation fails authorization."""

    def __init__(self, decision: MemoryAccessDecision) -> None:
        super().__init__(f"delegated memory access denied: {decision.reason}")
        self.decision = decision
        self.code = "MEMORY_DELEGATED_ACCESS_DENIED"


class AuthorizedSophiaGraphGateway:
    """Authorize untrusted calls while preserving raw-store compatibility."""

    def __init__(
        self,
        store: SophiaGraphStore,
        *,
        resolver: DelegationMemoryGrantResolver | None = None,
        audit_recorder: MemoryAuditRecorder = noop_audit_recorder,
        telemetry_recorder: MemoryAccessTelemetryRecorder = (
            noop_access_telemetry_recorder
        ),
    ) -> None:
        self._store = store
        self._resolver = resolver
        self._audit = audit_recorder
        self._telemetry = telemetry_recorder

    def decide(
        self,
        context: MemoryAccessContext,
        request: MemoryAccessRequest,
    ) -> MemoryAccessDecision:
        started = perf_counter()
        grant: DelegationMemoryGrant | None = None
        if context.delegated:
            if request.grant_id and self._resolver is not None:
                grant = self._resolver.resolve_grant(
                    request.grant_id,
                    context=context,
                    operation=request.operation,
                )
            if request.grant_id and grant is None:
                decision = MemoryAccessDecision(
                    allowed=False,
                    operation=request.operation,
                    reason="grant_unresolved",
                    grant_id=request.grant_id,
                    evidence_refs=context.evidence_refs,
                )
                self._record_decision(
                    context,
                    decision,
                    resolver_duration_ms=(perf_counter() - started) * 1000,
                )
                return decision
        decision = evaluate_memory_access(context, request, grant)
        self._record_decision(
            context,
            decision,
            resolver_duration_ms=(perf_counter() - started) * 1000,
        )
        return decision

    def require(
        self,
        context: MemoryAccessContext,
        request: MemoryAccessRequest,
    ) -> MemoryAccessDecision:
        """Return an allowed decision or raise the typed denial."""

        return self._require(context, request)

    def get_record(
        self,
        record_id: str,
        *,
        context: MemoryAccessContext,
        request: MemoryAccessRequest,
    ) -> MemoryRecord | None:
        decision = self.decide(context, request)
        if not decision.allowed:
            return None
        record = self._store.get_record(record_id)
        if record is None:
            return None
        if not self._record_allowed(record, decision):
            self._record_selector_denial(context, decision)
            return None
        return record

    def list_records(
        self,
        options: ListQueryOptions,
        *,
        context: MemoryAccessContext,
        request: MemoryAccessRequest,
    ) -> list[MemoryRecord]:
        decision = self._require(context, request)
        offset = max(int(options.offset or 0), 0)
        if offset >= decision.max_results:
            return []
        page_limit = min(
            options.limit or decision.max_results, decision.max_results - offset
        )
        narrowed = ListQueryOptions(
            scopes=list(options.scopes),
            types=list(decision.record_types or tuple(options.types or ())) or None,
            tiers=options.tiers,
            include_invalidated=options.include_invalidated,
            limit=page_limit,
            offset=offset,
            order_by=options.order_by,
            namespaces=list(decision.namespaces),
            as_of=options.as_of,
            valid_at=options.valid_at,
            effective_during=options.effective_during,
            believed_at=options.believed_at,
        )
        return [
            record
            for record in self._store.list_records(narrowed)
            if self._record_allowed(record, decision)
        ][:page_limit]

    def search_records(
        self,
        options: SearchQueryOptions,
        *,
        context: MemoryAccessContext,
        request: MemoryAccessRequest,
    ) -> list[MemoryRecord]:
        decision = self._require(context, request)
        narrowed = SearchQueryOptions(
            query=options.query,
            scopes=list(options.scopes),
            types=list(decision.record_types or tuple(options.types or ())) or None,
            tiers=options.tiers,
            filters=options.filters,
            include_invalidated=options.include_invalidated,
            limit=min(options.limit or decision.max_results, decision.max_results),
            namespaces=list(decision.namespaces),
            as_of=options.as_of,
            valid_at=options.valid_at,
            effective_during=options.effective_during,
            believed_at=options.believed_at,
        )
        return [
            record
            for record in self._store.search_records(narrowed)
            if self._record_allowed(record, decision)
        ][: decision.max_results]

    def put_record(
        self,
        record: MemoryRecord,
        *,
        context: MemoryAccessContext,
        request: MemoryAccessRequest,
    ) -> str:
        decision = self._require(context, request)
        if not self._record_allowed(record, decision):
            raise DelegatedMemoryAccessDeniedError(
                replace(decision, allowed=False, reason="selector_denied")
            )
        return self._store.put_record(record)

    def get_candidate(
        self,
        candidate_id: str,
        *,
        context: MemoryAccessContext,
        request: MemoryAccessRequest,
    ) -> MemoryCandidate | None:
        decision = self.decide(context, request)
        if not decision.allowed:
            return None
        candidate = self._store.get_candidate(candidate_id)
        if candidate is None:
            return None
        if not self._candidate_allowed(candidate, decision):
            self._record_selector_denial(context, decision)
            return None
        return candidate

    def list_candidates(
        self,
        options: CandidateListOptions,
        *,
        context: MemoryAccessContext,
        request: MemoryAccessRequest,
    ) -> list[MemoryCandidate]:
        decision = self._require(context, request)
        narrowed = CandidateListOptions(
            session_id=options.session_id,
            proposed_scope=options.proposed_scope,
            status=options.status,
            limit=min(options.limit or decision.max_results, decision.max_results),
            namespaces=list(decision.namespaces),
        )
        return [
            candidate
            for candidate in self._store.list_candidates(narrowed)
            if self._candidate_allowed(candidate, decision)
        ][: decision.max_results]

    def promote_candidate(
        self,
        candidate_id: str,
        target_scope: str,
        *,
        reviewer: str,
        context: MemoryAccessContext,
        request: MemoryAccessRequest,
    ) -> MemoryRecord:
        decision = self._require(context, request)
        candidate = self._store.get_candidate(candidate_id)
        if candidate is None or not self._candidate_allowed(candidate, decision):
            raise DelegatedMemoryAccessDeniedError(
                replace(decision, allowed=False, reason="selector_denied")
            )
        plan = build_candidate_promotion_plan(
            self._store,
            candidate_id=candidate_id,
            target_scope=target_scope,
            reviewer=reviewer,
        )
        result = apply_candidate_promotion_plan(
            self._store,
            plan,
            audit_recorder=self._audit,
        )
        record = self._store.get_record(result.record_id)
        if record is None:  # pragma: no cover - canonical store invariant
            raise RuntimeError("candidate promotion did not create a record")
        return record

    def review_candidate(
        self,
        decision_input: CandidateReviewDecision,
        *,
        context: MemoryAccessContext,
        request: MemoryAccessRequest,
    ) -> MemoryCandidate:
        decision = self._require(context, request)
        candidate = self._store.get_candidate(decision_input.candidate_id)
        if candidate is None or not self._candidate_allowed(candidate, decision):
            raise DelegatedMemoryAccessDeniedError(
                replace(decision, allowed=False, reason="selector_denied")
            )
        return apply_candidate_review(
            self._store,
            decision_input,
            audit_recorder=self._audit,
        )

    def list_links(
        self,
        options: LinkQueryOptions,
        *,
        context: MemoryAccessContext,
        request: MemoryAccessRequest,
    ) -> list[Any]:
        decision = self._require(context, request)
        if self.get_record(options.record_id, context=context, request=request) is None:
            return []
        narrowed = replace(
            options,
            namespaces=list(decision.namespaces),
            limit=min(options.limit or decision.max_results, decision.max_results),
        )
        links = self._store.list_links(narrowed)
        return [
            link
            for link in links
            if self._endpoint_allowed(link.source_record_id, decision)
            and (
                link.target_record_id is None
                or self._endpoint_allowed(link.target_record_id, decision)
            )
        ][: decision.max_results]

    def list_relations(
        self,
        record_id: str,
        *,
        context: MemoryAccessContext,
        request: MemoryAccessRequest,
        direction: str = "out",
        relation_types: list[Any] | None = None,
        limit: int | None = None,
    ) -> list[Any]:
        decision = self._require(context, request)
        if not self._endpoint_allowed(record_id, decision):
            return []
        relations = self._store.list_relations(
            record_id,
            direction=direction,
            relation_types=relation_types,
            limit=min(limit or decision.max_results, decision.max_results),
        )
        return [
            relation
            for relation in relations
            if self._endpoint_allowed(relation.source_record_id, decision)
            and self._endpoint_allowed(relation.target_record_id, decision)
        ][: decision.max_results]

    def get_local_graph(
        self,
        options: LocalGraphOptions,
        *,
        context: MemoryAccessContext,
        request: MemoryAccessRequest,
    ) -> GraphSnapshot:
        decision = self._require(context, request)
        if not self._endpoint_allowed(options.record_id, decision):
            return GraphSnapshot(nodes=[], edges=[], root_record_id=None)
        node_limit = min(options.max_nodes, decision.max_results)
        narrowed = replace(
            options,
            namespaces=list(decision.namespaces),
            max_nodes=node_limit,
            max_edges=min(options.max_edges, decision.max_results),
        )
        snapshot = self._store.get_local_graph(narrowed)
        allowed_ids = {
            node.record_id
            for node in snapshot.nodes
            if self._endpoint_allowed(node.record_id, decision)
        }
        return GraphSnapshot(
            nodes=[node for node in snapshot.nodes if node.record_id in allowed_ids],
            edges=[
                edge
                for edge in snapshot.edges
                if edge.source_record_id in allowed_ids
                and (
                    edge.target_record_id is None
                    or edge.target_record_id in allowed_ids
                )
            ],
            root_record_id=snapshot.root_record_id,
            depth=snapshot.depth,
            direction=snapshot.direction,
            provenance=dict(snapshot.provenance),
        )

    def run_federated_query(
        self,
        query: FederatedWorkspaceQuery,
        *,
        context: MemoryAccessContext,
        request: MemoryAccessRequest,
    ) -> FederatedWorkspaceResult:
        decision = self._require(context, request)
        workspaces = tuple(
            workspace
            for workspace in query.workspaces
            if workspace.workspace_id in decision.workspace_ids
        )
        if not workspaces:
            raise DelegatedMemoryAccessDeniedError(
                replace(decision, allowed=False, reason="workspace_denied")
            )
        explorer = replace(
            query.request,
            namespaces=list(decision.namespaces),
            limit=min(query.request.limit, decision.max_results),
        )
        return run_federated_workspace_query(
            replace(
                query,
                workspaces=workspaces,
                request=explorer,
                limit=min(query.limit, decision.max_results),
            )
        )

    def export_snapshot(
        self,
        options: MemoryBundleExportOptions,
        *,
        context: MemoryAccessContext,
        request: MemoryAccessRequest,
    ) -> Any:
        decision = self._require(context, request)
        narrowed = replace(
            options,
            limit=min(options.limit or decision.max_results, decision.max_results),
            namespaces=list(decision.namespaces),
        )
        return self._store.export_snapshot(narrowed)

    def import_snapshot(
        self,
        snapshot: MemoryBundleSnapshot,
        options: MemoryBundleImportOptions,
        *,
        context: MemoryAccessContext,
        request: MemoryAccessRequest,
    ) -> Any:
        decision = self._require(context, request)
        allowlist = list(decision.namespaces) or options.namespace_allowlist
        return self._store.import_snapshot(
            snapshot,
            replace(options, namespace_allowlist=allowlist),
        )

    def _require(
        self, context: MemoryAccessContext, request: MemoryAccessRequest
    ) -> MemoryAccessDecision:
        decision = self.decide(context, request)
        if not decision.allowed:
            raise DelegatedMemoryAccessDeniedError(decision)
        return decision

    @staticmethod
    def _record_allowed(record: MemoryRecord, decision: MemoryAccessDecision) -> bool:
        return namespace_matches_filters(
            record.effective_namespace, list(decision.namespaces)
        ) and (not decision.record_types or str(record.type) in decision.record_types)

    @staticmethod
    def _candidate_allowed(
        candidate: MemoryCandidate, decision: MemoryAccessDecision
    ) -> bool:
        namespace = candidate.namespace or candidate.proposed_scope
        resolved = (
            namespace
            if not isinstance(namespace, str)
            else MemoryNamespace.from_scope(namespace)
        )
        return namespace_matches_filters(resolved, list(decision.namespaces)) and (
            not decision.record_types or str(candidate.type) in decision.record_types
        )

    def _endpoint_allowed(self, record_id: str, decision: MemoryAccessDecision) -> bool:
        record = self._store.get_record(record_id)
        return record is not None and self._record_allowed(record, decision)

    def _record_decision(
        self,
        context: MemoryAccessContext,
        decision: MemoryAccessDecision,
        *,
        resolver_duration_ms: float = 0.0,
    ) -> None:
        self._audit(
            MemoryAuditEvent(
                event_type="memory.delegated_access.decision",
                target_kind="delegated_memory",
                details={
                    "allowed": decision.allowed,
                    "reason": decision.reason,
                    "operation": decision.operation,
                    "grant_bound": decision.grant_id is not None,
                    "namespace_count": len(decision.namespaces),
                    "workspace_count": len(decision.workspace_ids),
                    "max_results": decision.max_results,
                    "max_context_tokens": decision.max_context_tokens,
                },
            )
        )
        self._telemetry(
            MemoryAccessTelemetryEvent(
                operation=decision.operation,
                outcome="allow" if decision.allowed else "deny",
                reason=decision.reason,
                resolver_outcome=(
                    "not_required"
                    if not context.delegated
                    else "resolved"
                    if decision.allowed
                    else "failed"
                ),
                resolver_duration_ms=resolver_duration_ms,
                effective_max_results=decision.max_results,
                effective_max_context_tokens=decision.max_context_tokens,
            )
        )

    def _record_selector_denial(
        self, context: MemoryAccessContext, decision: MemoryAccessDecision
    ) -> None:
        self._record_decision(
            context,
            replace(decision, allowed=False, reason="selector_denied"),
        )


__all__ = ["AuthorizedSophiaGraphGateway", "DelegatedMemoryAccessDeniedError"]
