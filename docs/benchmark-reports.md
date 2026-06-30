# Benchmark Reports

Status: active

SophiaGraph includes a deterministic public benchmark and conformance suite for
package-level capability checks. It is not a performance shootout; it is a
repeatable compatibility scorecard.

Run JSON output:

```bash
python3.11 -m sophiagraph benchmark
```

Run Markdown output:

```bash
python3.11 -m sophiagraph benchmark --format markdown
```

Write a report file:

```bash
python3.11 -m sophiagraph benchmark --format markdown > docs/benchmarks/latest.md
```

A representative checked-in sample lives at
[`benchmarks/public-conformance-sample.md`](benchmarks/public-conformance-sample.md).

## Current groups

- graph navigation
- workspace round-trip
- interoperability
- privacy/export
- memory lifecycle
- view publish profiles
- backend parity
- OpenMinion direct-library handoff metadata

## Publication guidance

Published benchmark reports should include:

1. package version
2. benchmark version
3. fixture revision
4. exact command used
5. JSON or Markdown scorecard output

Do not publish machine-local paths, credentials, or provider-specific secrets in
benchmark reports.
