# Security Policy

## Reporting a vulnerability

Please do not open a public issue with exploit details.

Instead:

1. contact the project maintainers privately through the security reporting
   channel used for OpenMinion, or
2. if that channel is unavailable, open a minimal private coordination thread
   without exploit details and request a secure handoff path.

## Scope

This package's security posture follows the same general rules as OpenMinion:

1. report vulnerabilities privately first,
2. do not publish proof-of-exploit details before maintainers have had time to
   assess and respond,
3. include affected version, reproduction steps, and impact summary when
   possible.

## Package boundary

`sophiagraph` is a standalone package. Security reports should say whether the
issue affects:

1. the public standalone package surface (`src/sophiagraph/`),
2. package-local release tooling or tests, or
3. runtime/service behavior that belongs outside this package boundary
   (for example hosted transports, webhook delivery, schedulers, or browser
   runtime concerns owned by a service layer).

## Dependency note

Optional integrations such as local graph backends or host-managed provider
execution should be called out explicitly in reports. That helps determine
whether the issue is in the package-owned typed substrate or in an external
runtime/integration path.
