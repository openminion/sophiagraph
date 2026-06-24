"""SQLite typed graph persistence helpers."""

from __future__ import annotations

from dataclasses import replace as dc_replace
from typing import Any

from sophiagraph.contracts.errors import InvalidSupersessionError
from sophiagraph.portability.codec import json_dumps
from sophiagraph.storage.entity_episode_store import (
    RawEpisodeListOptions,
    validate_contradiction_references,
)
from sophiagraph.storage.graph_helpers import (
    contradiction_from_dict,
    contradiction_to_dict,
    decision_from_dict,
    decision_to_dict,
    entity_alias_from_dict,
    entity_alias_to_dict,
    entity_from_dict,
    entity_summary_from_dict,
    entity_summary_to_dict,
    entity_to_dict,
    episode_from_dict,
    episode_step_from_dict,
    episode_step_to_dict,
    episode_to_dict,
    fact_convergence_link_from_dict,
    fact_convergence_link_to_dict,
    fact_from_dict,
    fact_to_dict,
    outcome_from_dict,
    outcome_to_dict,
    procedure_from_dict,
    procedure_to_dict,
    raw_episode_from_dict,
    raw_episode_to_dict,
)

from .rows import namespace_filter_sql, row_json


class SqliteTypedGraphMixin:
    """Typed entity/fact/episode/procedure graph storage for SQLite."""

    def _ns_values(self, namespace) -> dict[str, Any]:
        return namespace.as_dict()

    def _ns_columns_clause(self, namespace_values: dict[str, Any]):
        cols = (
            "tenant_id",
            "org_id",
            "user_id",
            "agent_id",
            "session_id",
            "conversation_id",
            "project_id",
            "graph_id",
        )
        return tuple(namespace_values.get(col) for col in cols)

    def _ns_filter(self, namespaces):
        return namespace_filter_sql(namespaces)

    def put_entity(self, entity) -> str:
        payload = entity_to_dict(entity)
        ns_vals = self._ns_values(entity.namespace)
        cols = self._ns_columns_clause(ns_vals)
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_entities(
                    entity_id, canonical_name, entity_type, confidence,
                    invalidated_at,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id,
                    created_at, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entity.entity_id,
                    entity.canonical_name,
                    entity.entity_type,
                    float(entity.confidence),
                    entity.invalidated_at,
                    *cols,
                    entity.created_at,
                    entity.updated_at,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="entity",
                object_id=entity.entity_id,
                payload=payload,
                namespace=entity.namespace,
                schema_identifiers={
                    "node_label": "entity",
                    "entity_type": entity.entity_type,
                },
            )
        return entity.entity_id

    def get_entity(self, entity_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM sophiagraph_entities WHERE entity_id = ?",
                (entity_id,),
            ).fetchone()
        return None if row is None else entity_from_dict(row_json(row))

    def list_entities(
        self,
        *,
        namespaces=None,
        canonical_name=None,
        entity_type=None,
        include_invalidated=False,
        limit=None,
    ):
        clauses = ["1=1"]
        params: list[Any] = []
        if canonical_name:
            clauses.append("canonical_name = ?")
            params.append(canonical_name)
        if entity_type:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if not include_invalidated:
            clauses.append("invalidated_at IS NULL")
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_entities WHERE "
            + " AND ".join(clauses)
            + " ORDER BY canonical_name ASC, entity_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [entity_from_dict(row_json(row)) for row in rows]

    def put_entity_alias(self, alias) -> str:
        payload = entity_alias_to_dict(alias)
        ns_vals = self._ns_values(alias.namespace)
        cols = self._ns_columns_clause(ns_vals)
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_entity_aliases(
                    alias_id, alias_name, entity_id, original_entity_id, is_primary,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id,
                    created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alias.alias_id,
                    alias.alias_name,
                    alias.entity_id,
                    alias.original_entity_id,
                    1 if alias.is_primary else 0,
                    *cols,
                    alias.created_at,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="entity_alias",
                object_id=alias.alias_id,
                payload=payload,
                namespace=alias.namespace,
                schema_identifiers={
                    "node_label": "entity_alias",
                    "entity_id": alias.entity_id,
                },
            )
        return alias.alias_id

    def list_entity_aliases(
        self,
        *,
        entity_id=None,
        alias_name=None,
        namespaces=None,
        limit=None,
    ):
        clauses = ["1=1"]
        params: list[Any] = []
        if entity_id:
            clauses.append("entity_id = ?")
            params.append(entity_id)
        if alias_name:
            clauses.append("alias_name = ?")
            params.append(alias_name)
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_entity_aliases WHERE "
            + " AND ".join(clauses)
            + " ORDER BY alias_name ASC, alias_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [entity_alias_from_dict(row_json(row)) for row in rows]

    def put_fact(self, fact) -> str:
        payload = fact_to_dict(fact)
        ns_vals = self._ns_values(fact.namespace)
        cols = self._ns_columns_clause(ns_vals)
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_facts(
                    fact_id, subject_entity_id, predicate, object_entity_id,
                    object_literal, confidence, valid_from, valid_to,
                    observed_at, invalidated_at, superseded_by_fact_id,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id,
                    created_at, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fact.fact_id,
                    fact.subject_entity_id,
                    fact.predicate,
                    fact.object_entity_id,
                    fact.object_literal,
                    float(fact.confidence),
                    fact.valid_from,
                    fact.valid_to,
                    fact.observed_at,
                    fact.invalidated_at,
                    fact.superseded_by_fact_id,
                    *cols,
                    fact.created_at,
                    fact.updated_at,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="fact",
                object_id=fact.fact_id,
                payload=payload,
                namespace=fact.namespace,
                schema_identifiers={
                    "node_label": "fact",
                    "predicate": fact.predicate,
                },
            )
        return fact.fact_id

    def get_fact(self, fact_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM sophiagraph_facts WHERE fact_id = ?",
                (fact_id,),
            ).fetchone()
        return None if row is None else fact_from_dict(row_json(row))

    def list_facts(
        self,
        *,
        namespaces=None,
        subject_entity_id=None,
        object_entity_id=None,
        predicate=None,
        valid_at=None,
        learned_at=None,
        active_state="active",
        source_episode_id=None,
        include_invalidated=False,
        limit=None,
    ):
        clauses = ["1=1"]
        params: list[Any] = []
        if subject_entity_id:
            clauses.append("subject_entity_id = ?")
            params.append(subject_entity_id)
        if object_entity_id:
            clauses.append("object_entity_id = ?")
            params.append(object_entity_id)
        if predicate:
            clauses.append("predicate = ?")
            params.append(predicate)
        effective_state = "all" if include_invalidated else active_state
        if effective_state == "active":
            clauses.append("invalidated_at IS NULL AND superseded_by_fact_id IS NULL")
        elif effective_state == "historical":
            clauses.append(
                "(invalidated_at IS NOT NULL OR superseded_by_fact_id IS NOT NULL)"
            )
        if valid_at is not None:
            clauses.append("(valid_from IS NULL OR valid_from <= ?)")
            params.append(valid_at)
            clauses.append("(valid_to IS NULL OR valid_to > ?)")
            params.append(valid_at)
        if learned_at is not None:
            clauses.append("(observed_at IS NULL OR observed_at <= ?)")
            params.append(learned_at)
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_facts WHERE "
            + " AND ".join(clauses)
            + " ORDER BY observed_at DESC, fact_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        facts = [fact_from_dict(row_json(row)) for row in rows]
        if source_episode_id:
            facts = [f for f in facts if source_episode_id in f.source_episode_ids]
        return facts

    def record_contradiction(self, contradiction):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT fact_id FROM sophiagraph_facts WHERE fact_id IN (?, ?)",
                (contradiction.target_fact_id, contradiction.contradicting_fact_id),
            ).fetchall()
        known = {row["fact_id"] for row in rows}
        validate_contradiction_references(contradiction, known_fact_ids=known)

        if contradiction.decision in ("supersedes", "invalidates_target"):
            target = self.get_fact(contradiction.target_fact_id)
            if target is None:  # pragma: no cover - guarded above
                raise InvalidSupersessionError(
                    f"target fact missing after preflight: {contradiction.target_fact_id!r}"
                )
            if contradiction.decision == "supersedes":
                updated = dc_replace(
                    target,
                    invalidated_at=contradiction.decided_at,
                    superseded_by_fact_id=contradiction.contradicting_fact_id,
                )
            else:
                updated = dc_replace(target, invalidated_at=contradiction.decided_at)
            self.put_fact(updated)

        payload = contradiction_to_dict(contradiction)
        ns_vals = self._ns_values(contradiction.namespace)
        cols = self._ns_columns_clause(ns_vals)
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_contradictions(
                    contradiction_id, target_fact_id, contradicting_fact_id,
                    decision, deciding_actor, decided_at,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    contradiction.contradiction_id,
                    contradiction.target_fact_id,
                    contradiction.contradicting_fact_id,
                    contradiction.decision,
                    contradiction.deciding_actor,
                    contradiction.decided_at,
                    *cols,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="contradiction",
                object_id=contradiction.contradiction_id,
                payload=payload,
                namespace=contradiction.namespace,
                schema_identifiers={
                    "node_label": "contradiction",
                    "decision": contradiction.decision,
                },
            )
        return contradiction

    def list_contradictions(
        self,
        *,
        target_fact_id=None,
        contradicting_fact_id=None,
        namespaces=None,
        limit=None,
    ):
        clauses = ["1=1"]
        params: list[Any] = []
        if target_fact_id:
            clauses.append("target_fact_id = ?")
            params.append(target_fact_id)
        if contradicting_fact_id:
            clauses.append("contradicting_fact_id = ?")
            params.append(contradicting_fact_id)
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_contradictions WHERE "
            + " AND ".join(clauses)
            + " ORDER BY decided_at DESC, contradiction_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [contradiction_from_dict(row_json(row)) for row in rows]

    def put_entity_summary(self, summary) -> str:
        payload = entity_summary_to_dict(summary)
        ns_vals = self._ns_values(summary.namespace)
        cols = self._ns_columns_clause(ns_vals)
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_entity_summaries(
                    summary_id, entity_id,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id,
                    created_at, updated_at, invalidated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary.summary_id,
                    summary.entity_id,
                    *cols,
                    summary.created_at,
                    summary.updated_at,
                    summary.invalidated_at,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="entity_summary",
                object_id=summary.summary_id,
                payload=payload,
                namespace=summary.namespace,
                schema_identifiers={
                    "node_label": "entity_summary",
                    "entity_id": summary.entity_id,
                },
            )
        return summary.summary_id

    def get_entity_summary(self, summary_id):
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json
                FROM sophiagraph_entity_summaries
                WHERE summary_id = ?
                """,
                (summary_id,),
            ).fetchone()
        return None if row is None else entity_summary_from_dict(row_json(row))

    def list_entity_summaries(
        self,
        *,
        entity_id=None,
        namespaces=None,
        include_invalidated=False,
        limit=None,
    ):
        clauses = ["1=1"]
        params: list[Any] = []
        if entity_id:
            clauses.append("entity_id = ?")
            params.append(entity_id)
        if not include_invalidated:
            clauses.append("invalidated_at IS NULL")
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_entity_summaries WHERE "
            + " AND ".join(clauses)
            + " ORDER BY updated_at DESC, summary_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [entity_summary_from_dict(row_json(row)) for row in rows]

    def put_episode(self, episode) -> str:
        payload = episode_to_dict(episode)
        cols = self._ns_columns_clause(self._ns_values(episode.namespace))
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_episodes(
                    episode_id, title, status, started_at, ended_at,
                    parent_episode_id, task_id,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    episode.episode_id,
                    episode.title,
                    episode.status,
                    episode.started_at,
                    episode.ended_at,
                    episode.parent_episode_id,
                    episode.task_id,
                    *cols,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="episode",
                object_id=episode.episode_id,
                payload=payload,
                namespace=episode.namespace,
                schema_identifiers={"node_label": "episode", "status": episode.status},
            )
        return episode.episode_id

    def get_episode(self, episode_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM sophiagraph_episodes WHERE episode_id = ?",
                (episode_id,),
            ).fetchone()
        return None if row is None else episode_from_dict(row_json(row))

    def list_episodes(
        self,
        *,
        namespaces=None,
        status=None,
        task_id=None,
        artifact_id=None,
        tool_id=None,
        started_after=None,
        started_before=None,
        limit=None,
    ):
        clauses = ["1=1"]
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if task_id:
            clauses.append("task_id = ?")
            params.append(task_id)
        if started_after:
            clauses.append("started_at >= ?")
            params.append(started_after)
        if started_before:
            clauses.append("started_at <= ?")
            params.append(started_before)
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_episodes WHERE "
            + " AND ".join(clauses)
            + " ORDER BY started_at DESC, episode_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        episodes = [episode_from_dict(row_json(row)) for row in rows]
        if artifact_id:
            episodes = [ep for ep in episodes if artifact_id in ep.artifact_ids]
        if tool_id:
            episodes = [ep for ep in episodes if tool_id in ep.tool_ids]
        return episodes

    def put_episode_step(self, step) -> str:
        payload = episode_step_to_dict(step)
        cols = self._ns_columns_clause(self._ns_values(step.namespace))
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_episode_steps(
                    step_id, episode_id, sequence, kind, occurred_at,
                    tool_id, tool_call_id, artifact_id, file_path,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    step.step_id,
                    step.episode_id,
                    int(step.sequence),
                    step.kind,
                    step.occurred_at,
                    step.tool_id,
                    step.tool_call_id,
                    step.artifact_id,
                    step.file_path,
                    *cols,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="episode_step",
                object_id=step.step_id,
                payload=payload,
                namespace=step.namespace,
                schema_identifiers={"node_label": "episode_step", "kind": step.kind},
            )
        return step.step_id

    def list_episode_steps(self, *, episode_id, kind=None, limit=None):
        clauses = ["episode_id = ?"]
        params: list[Any] = [episode_id]
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        sql = (
            "SELECT payload_json FROM sophiagraph_episode_steps WHERE "
            + " AND ".join(clauses)
            + " ORDER BY sequence ASC, step_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [episode_step_from_dict(row_json(row)) for row in rows]

    def put_outcome(self, outcome) -> str:
        payload = outcome_to_dict(outcome)
        cols = self._ns_columns_clause(self._ns_values(outcome.namespace))
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_outcomes(
                    outcome_id, status, occurred_at, episode_id, step_id,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outcome.outcome_id,
                    outcome.status,
                    outcome.occurred_at,
                    outcome.episode_id,
                    outcome.step_id,
                    *cols,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="outcome",
                object_id=outcome.outcome_id,
                payload=payload,
                namespace=outcome.namespace,
                schema_identifiers={"node_label": "outcome", "status": outcome.status},
            )
        return outcome.outcome_id

    def list_outcomes(
        self,
        *,
        episode_id=None,
        step_id=None,
        status=None,
        namespaces=None,
        limit=None,
    ):
        clauses = ["1=1"]
        params: list[Any] = []
        if episode_id:
            clauses.append("episode_id = ?")
            params.append(episode_id)
        if step_id:
            clauses.append("step_id = ?")
            params.append(step_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_outcomes WHERE "
            + " AND ".join(clauses)
            + " ORDER BY occurred_at DESC, outcome_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [outcome_from_dict(row_json(row)) for row in rows]

    def put_decision(self, decision) -> str:
        payload = decision_to_dict(decision)
        cols = self._ns_columns_clause(self._ns_values(decision.namespace))
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_decisions(
                    decision_id, title, chosen, occurred_at, episode_id, step_id,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.decision_id,
                    decision.title,
                    decision.chosen,
                    decision.occurred_at,
                    decision.episode_id,
                    decision.step_id,
                    *cols,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="decision",
                object_id=decision.decision_id,
                payload=payload,
                namespace=decision.namespace,
                schema_identifiers={"node_label": "decision"},
            )
        return decision.decision_id

    def list_decisions(self, *, episode_id=None, namespaces=None, limit=None):
        clauses = ["1=1"]
        params: list[Any] = []
        if episode_id:
            clauses.append("episode_id = ?")
            params.append(episode_id)
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_decisions WHERE "
            + " AND ".join(clauses)
            + " ORDER BY occurred_at DESC, decision_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [decision_from_dict(row_json(row)) for row in rows]

    def put_procedure(self, procedure) -> str:
        payload = procedure_to_dict(procedure)
        cols = self._ns_columns_clause(self._ns_values(procedure.namespace))
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_procedures(
                    procedure_id, title, promotion_tier, created_at,
                    updated_at, invalidated_at,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    procedure.procedure_id,
                    procedure.title,
                    procedure.promotion_tier,
                    procedure.created_at,
                    procedure.updated_at,
                    procedure.invalidated_at,
                    *cols,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="procedure",
                object_id=procedure.procedure_id,
                payload=payload,
                namespace=procedure.namespace,
                schema_identifiers={
                    "node_label": "procedure",
                    "promotion_tier": procedure.promotion_tier,
                },
            )
        return procedure.procedure_id

    def get_procedure(self, procedure_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM sophiagraph_procedures WHERE procedure_id = ?",
                (procedure_id,),
            ).fetchone()
        return None if row is None else procedure_from_dict(row_json(row))

    def list_procedures(
        self,
        *,
        namespaces=None,
        promotion_tier=None,
        include_invalidated=False,
        limit=None,
    ):
        clauses = ["1=1"]
        params: list[Any] = []
        if promotion_tier:
            clauses.append("promotion_tier = ?")
            params.append(promotion_tier)
        if not include_invalidated:
            clauses.append("invalidated_at IS NULL")
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_procedures WHERE "
            + " AND ".join(clauses)
            + " ORDER BY updated_at DESC, procedure_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [procedure_from_dict(row_json(row)) for row in rows]

    def put_raw_episode(self, episode) -> str:
        payload = raw_episode_to_dict(episode)
        cols = self._ns_columns_clause(self._ns_values(episode.namespace))
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_raw_episodes(
                    episode_id, kind, source, source_id, occurred_at, ingested_at,
                    invalidated_at, actor,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    episode.episode_id,
                    episode.kind,
                    episode.source,
                    episode.source_id,
                    episode.occurred_at,
                    episode.ingested_at,
                    episode.invalidated_at,
                    episode.actor,
                    *cols,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="raw_episode",
                object_id=episode.episode_id,
                payload=payload,
                namespace=episode.namespace,
                schema_identifiers={
                    "node_label": "raw_episode",
                    "kind": episode.kind,
                },
            )
        return episode.episode_id

    def get_raw_episode(self, episode_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM sophiagraph_raw_episodes WHERE episode_id = ?",
                (episode_id,),
            ).fetchone()
        return None if row is None else raw_episode_from_dict(row_json(row))

    def list_raw_episodes(
        self,
        *,
        namespaces=None,
        kind=None,
        source=None,
        occurred_after=None,
        occurred_before=None,
        include_invalidated=False,
        limit=None,
    ):
        options = RawEpisodeListOptions(
            namespaces=namespaces,
            kind=kind,
            source=source,
            occurred_after=occurred_after,
            occurred_before=occurred_before,
            include_invalidated=include_invalidated,
            limit=limit,
        )
        clauses = ["1=1"]
        params: list[Any] = []
        if options.kind:
            clauses.append("kind = ?")
            params.append(options.kind)
        if options.source:
            clauses.append("source = ?")
            params.append(options.source)
        if options.occurred_after:
            clauses.append("occurred_at >= ?")
            params.append(options.occurred_after)
        if options.occurred_before:
            clauses.append("occurred_at <= ?")
            params.append(options.occurred_before)
        if not options.include_invalidated:
            clauses.append("invalidated_at IS NULL")
        ns_sql, ns_params = self._ns_filter(options.namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_raw_episodes WHERE "
            + " AND ".join(clauses)
            + " ORDER BY occurred_at DESC, episode_id ASC"
        )
        if options.limit is not None:
            sql += " LIMIT ?"
            params.append(int(options.limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [raw_episode_from_dict(row_json(row)) for row in rows]

    def put_fact_convergence_link(self, link) -> str:
        payload = fact_convergence_link_to_dict(link)
        cols = self._ns_columns_clause(self._ns_values(link.namespace))
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_fact_convergence_links(
                    link_id, fact_id, episode_id, role, confidence, created_at,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    link.link_id,
                    link.fact_id,
                    link.episode_id,
                    link.role,
                    float(link.confidence),
                    link.created_at,
                    *cols,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="fact_convergence_link",
                object_id=link.link_id,
                payload=payload,
                namespace=link.namespace,
                schema_identifiers={
                    "node_label": "fact_convergence_link",
                    "role": link.role,
                },
            )
        return link.link_id

    def list_fact_convergence_links(
        self,
        *,
        fact_id=None,
        episode_id=None,
        namespaces=None,
        limit=None,
    ):
        clauses = ["1=1"]
        params: list[Any] = []
        if fact_id:
            clauses.append("fact_id = ?")
            params.append(fact_id)
        if episode_id:
            clauses.append("episode_id = ?")
            params.append(episode_id)
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_fact_convergence_links WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at ASC, link_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [fact_convergence_link_from_dict(row_json(row)) for row in rows]


__all__ = ["SqliteTypedGraphMixin"]
