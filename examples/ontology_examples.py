"""Example ontology definitions for coding and research agents."""

from __future__ import annotations

from sophiagraph import SophiaGraphMemoryStore
from sophiagraph.models import (
    CategorySchema,
    EdgeTypeSchema,
    EntityTypeSchema,
    MemoryNamespace,
    OntologyDefinition,
    PropertySchema,
)


def coding_agent_ontology() -> OntologyDefinition:
    """Return a small coding-agent ontology."""

    return OntologyDefinition(
        ontology_id="coding-agent",
        version="1.0.0",
        owner="openminion-coding",
        namespace=MemoryNamespace(agent_id="coding"),
        compatibility="fresh",
        description="Example coding-agent ontology.",
        categories=[
            CategorySchema(name="Function"),
            CategorySchema(name="Module"),
            CategorySchema(name="Bug"),
            CategorySchema(name="Fix"),
        ],
        entity_types=[
            EntityTypeSchema(
                name="Function",
                properties=[
                    PropertySchema(name="language", value_type="str", required=True),
                    PropertySchema(name="line_count", value_type="int"),
                    PropertySchema(name="public", value_type="bool"),
                ],
            ),
            EntityTypeSchema(
                name="Module",
                properties=[
                    PropertySchema(name="path", value_type="str", required=True),
                    PropertySchema(name="line_count", value_type="int"),
                ],
            ),
            EntityTypeSchema(
                name="Bug",
                properties=[
                    PropertySchema(name="severity", value_type="str", required=True),
                    PropertySchema(name="reproducible", value_type="bool"),
                ],
            ),
            EntityTypeSchema(
                name="Fix",
                properties=[
                    PropertySchema(name="commit_sha", value_type="str"),
                ],
            ),
        ],
        edge_types=[
            EdgeTypeSchema(
                name="calls",
                source_entity_types=["Function"],
                target_entity_types=["Function"],
            ),
            EdgeTypeSchema(
                name="imports",
                source_entity_types=["Module"],
                target_entity_types=["Module"],
            ),
            EdgeTypeSchema(
                name="introduced_bug",
                source_entity_types=["Function", "Module"],
                target_entity_types=["Bug"],
            ),
            EdgeTypeSchema(
                name="fixed_bug",
                source_entity_types=["Fix"],
                target_entity_types=["Bug"],
            ),
        ],
    )


def research_agent_ontology() -> OntologyDefinition:
    """Return a small research-agent ontology."""

    return OntologyDefinition(
        ontology_id="research-agent",
        version="1.0.0",
        owner="openminion-research",
        namespace=MemoryNamespace(agent_id="research"),
        compatibility="fresh",
        description="Example research-agent ontology.",
        categories=[
            CategorySchema(name="Paper"),
            CategorySchema(name="Author"),
            CategorySchema(name="Claim"),
        ],
        entity_types=[
            EntityTypeSchema(
                name="Paper",
                properties=[
                    PropertySchema(name="title", value_type="str", required=True),
                    PropertySchema(name="published_at", value_type="datetime"),
                    PropertySchema(name="doi", value_type="str"),
                ],
            ),
            EntityTypeSchema(
                name="Author",
                properties=[
                    PropertySchema(
                        name="display_name", value_type="str", required=True
                    ),
                    PropertySchema(name="affiliations", value_type="list"),
                ],
            ),
            EntityTypeSchema(
                name="Claim",
                properties=[
                    PropertySchema(name="claim_text", value_type="str", required=True),
                    PropertySchema(name="confidence", value_type="float"),
                ],
            ),
        ],
        edge_types=[
            EdgeTypeSchema(
                name="authored_by",
                source_entity_types=["Paper"],
                target_entity_types=["Author"],
            ),
            EdgeTypeSchema(
                name="cites",
                source_entity_types=["Paper"],
                target_entity_types=["Paper"],
            ),
            EdgeTypeSchema(
                name="states_claim",
                source_entity_types=["Paper"],
                target_entity_types=["Claim"],
            ),
        ],
    )


def smoke_register_examples(store) -> dict[str, OntologyDefinition]:
    """Register both example ontologies against ``store`` via public APIs."""

    coding = coding_agent_ontology()
    research = research_agent_ontology()
    store.put_ontology(coding)
    store.put_ontology(research)
    return {"coding": coding, "research": research}


if __name__ == "__main__":
    s = SophiaGraphMemoryStore()
    registered = smoke_register_examples(s)
    for name, ontology in registered.items():
        print(
            f"{name}: {ontology.ontology_id}@{ontology.version} "
            f"(categories={len(ontology.categories)}, "
            f"entity_types={len(ontology.entity_types)}, "
            f"edge_types={len(ontology.edge_types)})"
        )
