"""In-memory sync, freshness, connector, and shared-block storage helpers."""

from __future__ import annotations

from sophiagraph.storage.graph_helpers import namespace_matches_filters


class MemorySyncStoreMixin:
    """Sync and collaboration storage surfaces for the in-memory store."""

    def put_sync_conflict(self, conflict):
        from sophiagraph.sync import sync_conflict_to_dict

        self._sync_conflicts[conflict.conflict_id] = conflict
        self._emit_change(
            object_type="sync_conflict",
            object_id=conflict.conflict_id,
            payload=sync_conflict_to_dict(conflict),
            namespace=conflict.namespace,
            schema_identifiers={"node_label": "sync_conflict", "kind": conflict.kind},
        )
        return conflict.conflict_id

    def get_sync_conflict(self, conflict_id):
        return self._sync_conflicts.get(conflict_id)

    def list_sync_conflicts(
        self,
        *,
        namespaces=None,
        status=None,
        source_id=None,
        limit=None,
    ):
        rows = [
            row
            for row in self._sync_conflicts.values()
            if namespace_matches_filters(row.namespace, namespaces)
        ]
        if status is not None:
            rows = [row for row in rows if row.status == status]
        if source_id is not None:
            rows = [row for row in rows if row.source_id == source_id]
        rows.sort(key=lambda row: (row.created_at, row.conflict_id), reverse=True)
        return rows[: int(limit)] if limit is not None else rows

    def put_freshness_entry(self, entry):
        from sophiagraph.freshness import freshness_entry_to_dict

        self._freshness_entries[entry.ledger_id] = entry
        self._emit_change(
            object_type="freshness_entry",
            object_id=entry.ledger_id,
            payload=freshness_entry_to_dict(entry),
            namespace=entry.namespace,
            schema_identifiers={
                "node_label": "freshness_entry",
                "source_kind": entry.source_kind,
            },
        )
        return entry.ledger_id

    def get_freshness_entry(self, ledger_id):
        return self._freshness_entries.get(ledger_id)

    def list_freshness_entries(
        self,
        *,
        namespaces=None,
        source_kind=None,
        source_id=None,
        status=None,
        limit=None,
    ):
        rows = [
            row
            for row in self._freshness_entries.values()
            if namespace_matches_filters(row.namespace, namespaces)
        ]
        if source_kind is not None:
            rows = [row for row in rows if row.source_kind == source_kind]
        if source_id is not None:
            rows = [row for row in rows if row.source_id == source_id]
        if status is not None:
            rows = [row for row in rows if row.status == status]
        rows.sort(key=lambda row: (row.updated_at, row.ledger_id), reverse=True)
        return rows[: int(limit)] if limit is not None else rows

    def put_source_entry(self, source):
        from sophiagraph.connectors import source_entry_to_dict

        self._source_entries[source.source_id] = source
        self._emit_change(
            object_type="source_registry",
            object_id=source.source_id,
            payload=source_entry_to_dict(source),
            namespace=source.namespace,
            schema_identifiers={
                "node_label": "source_registry",
                "source_type": source.source_type,
            },
        )
        return source.source_id

    def get_source_entry(self, source_id):
        return self._source_entries.get(source_id)

    def list_source_entries(
        self,
        *,
        namespaces=None,
        source_type=None,
        permission_scope=None,
        limit=None,
    ):
        rows = [
            row
            for row in self._source_entries.values()
            if namespace_matches_filters(row.namespace, namespaces)
        ]
        if source_type is not None:
            rows = [row for row in rows if row.source_type == source_type]
        if permission_scope is not None:
            rows = [row for row in rows if row.permission_scope == permission_scope]
        rows.sort(key=lambda row: row.source_id)
        return rows[: int(limit)] if limit is not None else rows

    def put_source_ingest(self, envelope):
        from sophiagraph.connectors import source_ingest_to_dict

        self._source_ingests[envelope.ingest_id] = envelope
        self._emit_change(
            object_type="source_ingest",
            object_id=envelope.ingest_id,
            payload=source_ingest_to_dict(envelope),
            namespace=envelope.namespace,
            schema_identifiers={
                "node_label": "source_ingest",
                "payload_kind": envelope.payload_kind,
            },
        )
        return envelope.ingest_id

    def get_source_ingest(self, ingest_id):
        return self._source_ingests.get(ingest_id)

    def put_shared_block_attachment(self, attachment):
        from sophiagraph.shared_blocks import shared_attachment_to_dict

        self._shared_attachments[attachment.attachment_id] = attachment
        self._emit_change(
            object_type="shared_block_attachment",
            object_id=attachment.attachment_id,
            payload=shared_attachment_to_dict(attachment),
            namespace=attachment.namespace,
            schema_identifiers={"node_label": "shared_block_attachment"},
        )
        return attachment.attachment_id

    def list_shared_block_attachments(
        self,
        *,
        block_id=None,
        namespaces=None,
        attached_agent_id=None,
        status=None,
        limit=None,
    ):
        rows = [
            row
            for row in self._shared_attachments.values()
            if namespace_matches_filters(row.namespace, namespaces)
        ]
        if block_id is not None:
            rows = [row for row in rows if row.block_id == block_id]
        if attached_agent_id is not None:
            rows = [row for row in rows if row.attached_agent_id == attached_agent_id]
        if status is not None:
            rows = [row for row in rows if row.status == status]
        rows.sort(key=lambda row: row.attachment_id)
        return rows[: int(limit)] if limit is not None else rows

    def put_shared_block_mirror(self, mirror):
        from sophiagraph.shared_blocks import shared_mirror_to_dict

        self._shared_mirrors[mirror.mirror_id] = mirror
        self._emit_change(
            object_type="shared_block_mirror",
            object_id=mirror.mirror_id,
            payload=shared_mirror_to_dict(mirror),
            namespace=mirror.mirror_namespace,
            schema_identifiers={"node_label": "shared_block_mirror"},
        )
        return mirror.mirror_id

    def get_shared_block_mirror(self, mirror_id):
        return self._shared_mirrors.get(mirror_id)

    def list_shared_block_mirrors(
        self,
        *,
        block_id=None,
        namespaces=None,
        status=None,
        limit=None,
    ):
        rows = [
            row
            for row in self._shared_mirrors.values()
            if namespace_matches_filters(row.mirror_namespace, namespaces)
        ]
        if block_id is not None:
            rows = [row for row in rows if row.block_id == block_id]
        if status is not None:
            rows = [row for row in rows if row.status == status]
        rows.sort(key=lambda row: row.mirror_id)
        return rows[: int(limit)] if limit is not None else rows

    def put_shared_block_conflict(self, conflict):
        from sophiagraph.shared_blocks import shared_conflict_to_dict

        self._shared_conflicts[conflict.conflict_id] = conflict
        self._emit_change(
            object_type="shared_block_conflict",
            object_id=conflict.conflict_id,
            payload=shared_conflict_to_dict(conflict),
            namespace=conflict.namespace,
            schema_identifiers={"node_label": "shared_block_conflict"},
        )
        return conflict.conflict_id

    def list_shared_block_conflicts(
        self,
        *,
        block_id=None,
        namespaces=None,
        status=None,
        limit=None,
    ):
        rows = [
            row
            for row in self._shared_conflicts.values()
            if namespace_matches_filters(row.namespace, namespaces)
        ]
        if block_id is not None:
            rows = [row for row in rows if row.block_id == block_id]
        if status is not None:
            rows = [row for row in rows if row.status == status]
        rows.sort(key=lambda row: row.created_at, reverse=True)
        return rows[: int(limit)] if limit is not None else rows

    def put_shared_block_usage_event(self, event):
        from sophiagraph.shared_blocks import shared_usage_to_dict

        self._shared_usage_events[event.event_id] = event
        self._emit_change(
            object_type="shared_block_usage",
            object_id=event.event_id,
            payload=shared_usage_to_dict(event),
            namespace=event.namespace,
            schema_identifiers={
                "node_label": "shared_block_usage",
                "action": event.action,
            },
        )
        return event.event_id

    def list_shared_block_usage_events(
        self,
        *,
        block_id=None,
        namespaces=None,
        action=None,
        limit=None,
    ):
        rows = [
            row
            for row in self._shared_usage_events.values()
            if namespace_matches_filters(row.namespace, namespaces)
        ]
        if block_id is not None:
            rows = [row for row in rows if row.block_id == block_id]
        if action is not None:
            rows = [row for row in rows if row.action == action]
        rows.sort(key=lambda row: row.occurred_at, reverse=True)
        return rows[: int(limit)] if limit is not None else rows
