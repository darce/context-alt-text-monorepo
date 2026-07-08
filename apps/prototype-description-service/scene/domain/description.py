"""Domain enums for the image-description contract.

StrEnums centralize the description status/provenance vocabularies (sr-007) so no
magic strings scatter across the route, service, and persistence layers.
"""

from __future__ import annotations

from enum import StrEnum


class DescriptionAdapterKind(StrEnum):
    """Which DescriptionAdapter produced a result."""

    SEEDED = "seeded"
    LOCAL_CPU = "local_cpu"
    GPU = "gpu"
    HOSTED_PROVIDER = "hosted_provider"


class RetentionClass(StrEnum):
    """Retention disposition of a generated description.

    Mirrors the canonical recognition retention vocabulary
    (``recognition/interface_adapters/http/routers/retention.py`` ``RETENTION_MODES``),
    which is a plain set of literals with no importable enum. Defined here as a
    StrEnum so the description contract validates the same tokens without coupling
    ``scene`` to a heavy HTTP-router import — keep the two token sets in sync.
    """

    RETAIN_ALL = "retain_all"
    DISPOSE_AFTER_ACK = "dispose_after_ack"
    PURGE_ON_DEMAND = "purge_on_demand"


class ProviderMode(StrEnum):
    """Where image bytes were processed, for provider disclosure.

    ``none``/``local`` keep bytes inside the Alt Context boundary; ``hosted``
    means bytes left to a third-party provider (Phase 5+, opt-in only).
    """

    NONE = "none"
    LOCAL = "local"
    HOSTED = "hosted"


class DescriptionResultTier(StrEnum):
    """Whether a description is a CPU fallback or the final GPU result."""

    PROVISIONAL_CPU = "provisional_cpu"
    FINAL_GPU = "final_gpu"
