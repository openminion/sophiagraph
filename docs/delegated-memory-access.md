# Delegated Memory Access

Sophiagraph stores typed knowledge but does not decide who may delegate access.
A host such as OpenMinion issues and revokes grants. Sophiagraph consumes a
bounded projection through `DelegationMemoryGrantResolver` and evaluates it at
the `AuthorizedSophiaGraphGateway` boundary.

## Trust Boundary

- Raw stores are trusted package infrastructure for local in-process callers.
- Remote agents, plugins, HTTP/MCP handlers, and other untrusted adapters use
  the authorized gateway.
- A grant ID is a correlation reference, not a bearer credential.
- The trusted principal, audience, parent/child run lineage, selectors,
  operations, record types, issuance, expiry, depth, and budgets must all
  agree.
- A delegated grant is active only when the operation starts at or after
  `issued_at` and before `expires_at`; before-issued and expired grants both
  fail closed without exposing content or hidden identifiers.
- Grant resolution runs for each operation so a later revoke or cancellation
  blocks new reads, retries, and resumes.
- Revocation cannot retract context already delivered to a model.

The package does not infer authorization, ownership, sensitivity, or sharing
intent from prose. It also does not create relations from child output.

## Host Integration

1. Keep grant persistence and revocation in the host policy owner.
2. Implement `DelegationMemoryGrantResolver` against that authority.
3. Build `MemoryAccessContext` only from authenticated runtime state.
4. Map a request into `MemoryAccessRequest` with explicit selectors and bounds.
5. Call `AuthorizedSophiaGraphGateway`; do not expose the raw store to the
   delegated caller.
6. Submit child-authored durable knowledge as a parent-owned candidate, then
   use the existing reviewer and promotion flow.

The v1 delegated posture is read-only and bounded. Writable shared memory and
transitive re-sharing remain refused unless a later contract explicitly adds
their concurrency and authority rules.

## Migration and Rollback

Migration is additive: existing trusted local store consumers continue to use
the raw store. Move one remote or delegated entrypoint at a time to the gateway,
then verify direct-ID, list/search, graph, candidate, and export denials before
moving the next entrypoint.

To roll back a host integration, stop issuing delegated grants and remove the
remote route while retaining local trusted use. Do not copy grants into
Sophiagraph or fall back to an empty selector as unrestricted access. Stored
knowledge and portability bundles do not require a data migration because the
authorization layer does not change record ownership or storage format.
