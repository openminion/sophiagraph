# Sophiagraph Code Quality and Hygiene

This is the public contributor version of the package's code-quality rules.

The short version:

1. keep durable-memory contracts typed and explicit,
2. keep package boundaries honest,
3. keep runtime behavior structural rather than speculative,
4. keep comments minimal,
5. and prove the change with validation.

## 1. Prefer one truthful owner

Use the nearest clear owner:

1. typed records and domain DTOs in `models/`
2. query request/result shapes in `query/`
3. storage behavior in `storage/`
4. portability codecs in `portability/`
5. package-owned trust, temporal, and audit contracts in their named
   subpackages

Avoid:

1. duplicate helpers,
2. repeated magic literals,
3. ad hoc wrappers around canonical package owners.

## 2. Keep runtime behavior structural, not speculative

Runtime code should enforce structure, policy, and safety. It should not guess
meaning that belongs to hosts, operators, or models.

Avoid:

1. local semantic heuristics deciding intent,
2. silent edge promotion,
3. provider SDK behavior inside the core package.

Prefer:

1. typed fields,
2. explicit contracts,
3. deterministic policies,
4. clear owner boundaries.

## 3. Keep names and layout honest

Rules:

1. remove stale names instead of letting them linger,
2. keep files in the package area that truthfully owns them,
3. do not grow generic junk-drawer files like `utils.py`.

## 4. Keep public docs portable

Do not add:

1. machine-local absolute paths,
2. private workstation assumptions,
3. internal tracker-state wording as public package documentation.

## 5. Keep changes focused

Good practice:

1. one clear purpose per PR,
2. update tests near the change,
3. avoid unrelated refactors in the same patch.

## 6. Validate before calling work done

Before closing work, run the package gates from `sophiagraph/`:

```bash
make lint
make test
```

If your change affects packaging or public release shape, also run:

```bash
make release-check
```

## 7. When in doubt, choose clarity over cleverness

The package prefers:

1. explicit owners over convenience,
2. typed deterministic surfaces over magical ones,
3. maintainable structure over short-term shortcuts.
