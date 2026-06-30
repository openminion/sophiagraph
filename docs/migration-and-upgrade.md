# Migration and Upgrade Guide

Status: active

SophiaGraph keeps migrations explicit. Do not upgrade a durable workspace or
database in-place without a backup and a focused smoke check.

## Before upgrading

```bash
python3.11 scripts/release_check.py --skip-twine
```

For durable local data:

1. Export a bundle or create a storage backup.
2. Record the installed package version.
3. Run the upgrade in a disposable environment first when possible.

## SQLite stores

SQLite schema changes are package-owned and versioned by the store. The upgrade
path should be:

1. Stop concurrent writers.
2. Create a backup.
3. Install the new package.
4. Open the store once to apply migrations.
5. Run a smoke query or `sophiagraph-smoke`.

## Portability bundles

Bundles are the safest cross-version handoff format when moving between
machines or host runtimes. Export from the old runtime, import into the new
runtime, then verify record counts, namespace filters, and relation counts.

## Optional graph backends

Optional graph backends such as Kuzu and Neo4j should be treated as derived
indexes unless the host runtime declares otherwise. Rebuild or re-upsert the
graph export batch after package upgrades that change graph export shape.

## UI artifacts

Local UI preview files are generated artifacts. Regenerate them after upgrading
instead of carrying old HTML or report files forward as source.

## Rollback

Rollback should restore from a pre-upgrade backup or bundle. Avoid manually
editing SQLite files, graph backend files, or generated UI artifacts.
