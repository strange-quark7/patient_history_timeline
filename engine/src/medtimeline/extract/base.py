"""The swappable extraction contract.

Cloud and local extractors both implement `Extractor`. Pick one by name with
`get_extractor`, so switching to offline is a settings change.
"""

from __future__ import annotations

from typing import Callable, Protocol

from medtimeline.ingest import PageInput
from medtimeline.schema import PageExtraction


class ExtractionError(RuntimeError):
    pass


class Extractor(Protocol):
    name: str

    def extract(self, page: PageInput) -> PageExtraction: ...


_REGISTRY: dict[str, Callable[..., Extractor]] = {}


def register(name: str):
    def deco(factory: Callable[..., Extractor]):
        _REGISTRY[name] = factory
        return factory

    return deco


def get_extractor(name: str, **kwargs) -> Extractor:
    # Import built-ins lazily so optional dependencies stay optional.
    from medtimeline.extract import claude, fixture  # noqa: F401

    if name not in _REGISTRY:
        raise ValueError(f"Unknown extractor '{name}'. Available: {', '.join(sorted(_REGISTRY))}")
    return _REGISTRY[name](**kwargs)


def available_extractors() -> list[str]:
    from medtimeline.extract import claude, fixture  # noqa: F401

    return sorted(_REGISTRY)
