# Support

## What is supported today

Current public standalone support is limited to:

1. the typed wisdom-graph package surface documented in `README.md`,
   `API_COMPATIBILITY.md`, and `docs/`,
2. package-owned local storage, query, portability, workspace, sync, UI
   contract, and interoperability helpers, and
3. the release/install smoke and package-local test workflow needed to validate
   the published package.

## Not covered by the standalone public support promise

The following surfaces are outside the current standalone package support
promise:

1. hosted or browser runtime behavior owned by a service layer,
2. scheduler, webhook-delivery, or transport behavior outside this package,
3. monorepo planning docs and tracker execution artifacts,
4. third-party provider infrastructure, paid services, or host-specific
   deployment wiring.

## Getting help

For usage questions or bug reports:

1. include the package version,
2. include the exact import path or command you ran,
3. state whether the issue affects the public standalone surface or an
   out-of-package runtime/integration surface,
4. include traceback or reproduction steps when available.

If the issue only reproduces inside a larger host runtime, call that out
explicitly; that usually means the problem is on an integration-owned path
rather than the standalone package contract.
