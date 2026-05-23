"""Typed trust contracts for the memory poisoning-defense lane."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sophiagraph.contracts.errors import InvalidArgumentError


ClaimKeyPolarity = Literal["asserts", "negates"]
MemorySourceClass = Literal[
    "user_input",
    "tool_result",
    "llm_extracted",
    "agent_inferred",
    "imported_bundle",
]


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass(frozen=True)
class TrustScore:
    source_provenance: float
    corroboration: float
    contradiction_penalty: float
    rate_limit_pressure: float
    score: float

    def __post_init__(self) -> None:
        if self.contradiction_penalty < 0.0:
            raise InvalidArgumentError("contradiction_penalty must be non-negative")
        object.__setattr__(
            self,
            "source_provenance",
            _clamp01(self.source_provenance),
        )
        object.__setattr__(self, "corroboration", _clamp01(self.corroboration))
        object.__setattr__(
            self,
            "contradiction_penalty",
            _clamp01(self.contradiction_penalty),
        )
        object.__setattr__(
            self,
            "rate_limit_pressure",
            _clamp01(self.rate_limit_pressure),
        )
        object.__setattr__(self, "score", _clamp01(self.score))
