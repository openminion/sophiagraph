"""Check or refresh the stable top-level public API manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import sophiagraph
from sophiagraph.compatibility import build_public_api_manifest


def _stable_payload() -> dict[str, object]:
    manifest = build_public_api_manifest(sophiagraph).to_dict()
    dependencies = [
        {"package": item["package"], "required_range": item["required_range"]}
        for item in manifest["dependencies"]
    ]
    return {
        "report_version": manifest["report_version"],
        "package_version": manifest["package_version"],
        "exports": list(manifest["exports"]),
        "dependencies": dependencies,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    baseline = root / "scripts" / "baselines" / "public_api.json"
    observed = _stable_payload()
    payload = json.dumps(observed, indent=2, sort_keys=True) + "\n"
    if args.write:
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text(payload, encoding="utf-8")
        print(f"wrote {baseline.relative_to(root)}")
        return 0
    if not baseline.is_file():
        print("public API baseline missing", file=sys.stderr)
        return 1
    expected = json.loads(baseline.read_text(encoding="utf-8"))
    if observed != expected:
        print("public API drift; run scripts/check_api.py --write", file=sys.stderr)
        return 1
    print("public-api: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
