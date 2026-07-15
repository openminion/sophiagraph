"""Public API and dependency compatibility reporting."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib import metadata
from types import ModuleType
from typing import Any, Final, cast

GRAPHFAKOS_MIN_VERSION: Final[tuple[int, int, int]] = (0, 0, 5)
GRAPHFAKOS_MAX_MAJOR_EXCLUSIVE: Final[int] = 1
COMPATIBILITY_REPORT_VERSION: Final[str] = "sophiagraph.compatibility.v1"


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts = value.split("+", 1)[0].split("-", 1)[0].split(".")
    numeric = [int(part) if part.isdigit() else 0 for part in parts[:3]]
    return cast(tuple[int, int, int], tuple((numeric + [0, 0, 0])[:3]))


@dataclass(frozen=True, slots=True)
class DependencyCompatibility:
    package: str
    installed_version: str | None
    supported: bool
    required_range: str


@dataclass(frozen=True, slots=True)
class PublicApiManifest:
    report_version: str
    package_version: str
    exports: tuple[str, ...]
    dependencies: tuple[DependencyCompatibility, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def graphfakos_compatibility(version: str | None = None) -> DependencyCompatibility:
    detected = version
    if detected is None:
        try:
            detected = metadata.version("graphfakos")
        except metadata.PackageNotFoundError:
            detected = None
    parsed = _version_tuple(detected) if detected is not None else None
    supported = bool(
        parsed is not None
        and parsed >= GRAPHFAKOS_MIN_VERSION
        and parsed[0] < GRAPHFAKOS_MAX_MAJOR_EXCLUSIVE
    )
    return DependencyCompatibility(
        package="graphfakos",
        installed_version=detected,
        supported=supported,
        required_range=">=0.0.5,<1",
    )


def build_public_api_manifest(module: ModuleType) -> PublicApiManifest:
    exports = tuple(sorted(str(name) for name in getattr(module, "__all__", ())))
    return PublicApiManifest(
        report_version=COMPATIBILITY_REPORT_VERSION,
        package_version=str(getattr(module, "__version__", "unknown")),
        exports=exports,
        dependencies=(graphfakos_compatibility(),),
    )


__all__ = [
    "COMPATIBILITY_REPORT_VERSION",
    "DependencyCompatibility",
    "GRAPHFAKOS_MAX_MAJOR_EXCLUSIVE",
    "GRAPHFAKOS_MIN_VERSION",
    "PublicApiManifest",
    "build_public_api_manifest",
    "graphfakos_compatibility",
]
