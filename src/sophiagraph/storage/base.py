"""Stable public storage protocol for the reusable ``sophiagraph`` package."""

from __future__ import annotations

from typing import Protocol

from sophiagraph.contracts.types import MEMORY_CONTRACT_VERSION
from sophiagraph.storage.protocol_core import CoreSophiaGraphStore
from sophiagraph.storage.protocol_extended import ExtendedSophiaGraphStore


class SophiaGraphStore(CoreSophiaGraphStore, ExtendedSophiaGraphStore, Protocol):
    """Combined durable engine contract for ``sophiagraph`` consumers."""

    contract_version: str = MEMORY_CONTRACT_VERSION
