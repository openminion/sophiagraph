# Sophiagraph UI Contracts

`sophiagraph.ui` is the package-owned typed boundary for future operator-facing
memory and wisdom-graph screens.

The ownership split is explicit:

1. `sophiagraph` owns typed durable-memory contracts and the package-local UI
   boundary surface,
2. `sophiagraph-server` or another host runtime owns the actual browser,
   transport, auth, and operator experience.

Current contract:

- owner import root: `sophiagraph.ui`
- runtime package: `sophiagraph-server`
- transport kind: `rest`
- transport status: `designed_not_implemented`
- current API seam: `sophiagraph-server`

The current screen manifest stays intentionally structural:

1. explore
2. record detail
3. graph
4. operations
5. repair
6. community
7. timeline
8. schema

This package does **not** currently ship a browser app, Textual TUI, daemon,
or hosted admin UI. It only ships the typed boundary contract so the standalone
package has one canonical import root for future visual/runtime work.
