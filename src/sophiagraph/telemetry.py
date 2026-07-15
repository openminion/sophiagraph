"""Low-cardinality telemetry contracts with optional OpenTelemetry wiring."""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
from time import monotonic
from types import TracebackType
from typing import Any, Mapping, Protocol

_ALLOWED_ATTRIBUTES = frozenset(
    {
        "backend",
        "operation",
        "outcome",
        "object_type",
        "stage",
        "transport",
        "tenant_present",
        "namespace_present",
    }
)


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    name: str
    duration_ms: float
    attributes: Mapping[str, Any] = field(default_factory=dict)


class TelemetrySink(Protocol):
    def record(self, event: TelemetryEvent) -> None: ...


class NullTelemetrySink:
    def record(self, event: TelemetryEvent) -> None:
        del event


class OpenTelemetrySink:
    """Lazy OpenTelemetry adapter; query text and payloads are never recorded."""

    def __init__(self, *, tracer_name: str = "sophiagraph") -> None:
        try:
            trace = importlib.import_module("opentelemetry.trace")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "OpenTelemetry support requires `pip install sophiagraph[telemetry]`"
            ) from exc
        self._tracer = trace.get_tracer(tracer_name)

    def record(self, event: TelemetryEvent) -> None:
        with self._tracer.start_as_current_span(event.name) as span:
            span.set_attribute("sophiagraph.duration_ms", event.duration_ms)
            for key, value in event.attributes.items():
                span.set_attribute(f"sophiagraph.{key}", value)


def safe_telemetry_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in attributes.items()
        if key in _ALLOWED_ATTRIBUTES and isinstance(value, (str, int, float, bool))
    }


class _OperationTrace:
    def __init__(
        self,
        sink: TelemetrySink,
        name: str,
        attributes: Mapping[str, Any] | None,
    ) -> None:
        self._sink = sink
        self._name = name
        self._attributes = attributes
        self._started = 0.0

    def __enter__(self) -> None:
        self._started = monotonic()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        safe = safe_telemetry_attributes(self._attributes or {})
        safe["outcome"] = "error" if exc_type is not None else "ok"
        self._sink.record(
            TelemetryEvent(
                name=self._name,
                duration_ms=(monotonic() - self._started) * 1000.0,
                attributes=safe,
            )
        )


def trace_operation(
    sink: TelemetrySink,
    name: str,
    *,
    attributes: Mapping[str, Any] | None = None,
) -> _OperationTrace:
    return _OperationTrace(sink, name, attributes)


__all__ = [
    "NullTelemetrySink",
    "OpenTelemetrySink",
    "TelemetryEvent",
    "TelemetrySink",
    "safe_telemetry_attributes",
    "trace_operation",
]
