"""Example schemas validate through the public API."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from sophiagraph import SophiaGraphMemoryStore, SophiaGraphSqliteStore

_HERE = Path(__file__).resolve().parent
_EXAMPLE = _HERE.parent / "examples" / "ontology_examples.py"


def _load_examples():
    spec = importlib.util.spec_from_file_location("ontology_examples", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "sg.sqlite3")


def test_example_ontologies_register_and_round_trip(store) -> None:
    module = _load_examples()
    registered = module.smoke_register_examples(store)
    assert {"coding", "research"} == set(registered.keys())
    # Round-trip both through the store.
    coding = store.get_ontology(ontology_id="coding-agent", version="1.0.0")
    research = store.get_ontology(ontology_id="research-agent", version="1.0.0")
    assert coding is not None and len(coding.entity_types) == 4
    assert research is not None and len(research.edge_types) == 3


def test_example_ontologies_have_no_hard_coded_domain_runtime_behavior() -> None:
    """The examples module is data + a smoke helper; nothing else."""
    module = _load_examples()
    public_callables = {
        name
        for name in dir(module)
        if not name.startswith("_")
        and callable(getattr(module, name))
        and getattr(getattr(module, name), "__module__", "") == "ontology_examples"
    }
    # Only the constructors + the smoke helper.
    assert public_callables == {
        "coding_agent_ontology",
        "research_agent_ontology",
        "smoke_register_examples",
    }
