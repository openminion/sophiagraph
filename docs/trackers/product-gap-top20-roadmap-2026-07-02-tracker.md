# Sophiagraph Product Gap Top 20 Roadmap Tracker

Date: 2026-07-02
Status: draft discussion, not executable
Owner: Sophiagraph
Related:
[`../specs/product-gap-top20-roadmap-2026-07-02-spec.md`](../specs/product-gap-top20-roadmap-2026-07-02-spec.md),
[`../storage-retrieval-backends.md`](../storage-retrieval-backends.md),
[`../retrieval-boundary.md`](../retrieval-boundary.md),
[`../human-management.md`](../human-management.md),
[`../workspace-mode.md`](../workspace-mode.md),
[`../ui-workbench.md`](../ui-workbench.md),
[`../vector-conformance.md`](../vector-conformance.md)

## Purpose

Track discussion of the next twenty Sophiagraph product gaps. This tracker is
a candidate register only. It does not authorize implementation.

## Execution Gate

Do not start code from this tracker. Promote exactly one bounded item into a
new executable tracker when it is ready for implementation.

Promotion must preserve these rules:

1. approved memory knowledge stays governed,
2. human notes and agent memories share storage and deletion semantics,
3. optional graph/vector dependencies stay optional and capability-reported,
4. hosted services and background sync need separate scope decisions,
5. no version bump happens unless explicitly requested.

## Candidate Board

| ID | Priority | Class | Status | Candidate | Promotion target |
| --- | --- | --- | --- | --- | --- |
| `SGT20-01` | P0 | human management | `todo` | Human note manager depth. | Recommended first executable tracker. |
| `SGT20-02` | P0 | import | `todo` | Bulk import and preview pipeline. | New import-preview tracker. |
| `SGT20-03` | P0 | retrieval | `todo` | Retrieval evidence unification. | Recommended early executable tracker. |
| `SGT20-04` | P0 | governance | `todo` | Trust and governance claim alignment. | New claim-alignment tracker. |
| `SGT20-05` | P1 | temporal | `todo` | Temporal memory timelines. | New temporal-workbench tracker. |
| `SGT20-06` | P1 | namespace | `todo` | Namespace and actor administration. | New governance-admin tracker. |
| `SGT20-07` | P0 | lifecycle | `todo` | Deletion, tombstone, and vector orphan lifecycle. | New deletion/vector lifecycle tracker. |
| `SGT20-08` | P0 | capability | `todo` | Store capability UI and CLI. | Recommended early executable tracker. |
| `SGT20-09` | P2 | optional backend | `todo` | Optional Zvec vector adapter. | Deferred until optional dependency policy is accepted. |
| `SGT20-10` | P2 | optional backend | `todo` | Optional LanceDB vector adapter. | Deferred until concrete consumer exists. |
| `SGT20-11` | P2 | boundary reserve | `todo` | Remote vector adapter reserve. | Boundary and privacy acceptance before implementation. |
| `SGT20-12` | P2 | optional backend | `todo` | Kuzu/Neo4j graph conformance depth. | Deferred until graph traversal demand proves value. |
| `SGT20-13` | P1 | MCP | `todo` | MCP memory service proof. | Package or sibling-server tracker after scope review. |
| `SGT20-14` | P0 | UI | `todo` | Workbench navigation polish. | Recommended early executable tracker. |
| `SGT20-15` | P0 | portability | `todo` | Portable bundle verification. | Recommended early executable tracker. |
| `SGT20-16` | P1 | privacy | `todo` | Privacy and redaction profiles. | New export/privacy tracker. |
| `SGT20-17` | P1 | workflow | `todo` | Memory candidate queue. | New candidate workflow tracker. |
| `SGT20-18` | P1 | eval | `todo` | Retrieval eval scorecards. | New retrieval-eval tracker. |
| `SGT20-19` | P1 | runtime-adjacent | `todo` | Sophia-to-Pragma citation policy. | Separate boundary/runtime tracker. |
| `SGT20-20` | P1 | examples | `todo` | Public recipes and sample datasets. | New examples and smoke tracker. |

## Suggested First Promotion

Promote `SGT20-01` first.

Reason:

1. it closes the most visible standalone-memory gap,
2. it strengthens the human-managed note loop already documented in public
   docs,
3. it has no optional dependency or hosted-service dependency,
4. it makes later import, workbench, and retrieval-evidence work easier to
   validate.

## Boundary Reserves

Rows that must not be implemented directly from this tracker:

1. `SGT20-09` Zvec adapter,
2. `SGT20-10` LanceDB adapter,
3. `SGT20-11` hosted vector adapters,
4. hosted or long-running variants of `SGT20-13`,
5. runtime-owned parts of `SGT20-19`.

## Validation Expectations For Promoted Rows

Every promoted row should include:

1. focused pytest coverage,
2. targeted Ruff over touched source/tests/examples,
3. `PYTHONDONTWRITEBYTECODE=1 make check`,
4. `PYTHONDONTWRITEBYTECODE=1 make release-check` when public imports,
   packaging, examples, UI artifacts, or release surfaces change,
5. docs updates for any public CLI/API behavior.

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-02 | Created review-only top-20 gap register from current package state and public product/open-source research. |
