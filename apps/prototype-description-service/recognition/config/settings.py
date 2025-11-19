"""Settings loader for the recognition subsystem."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Tuple

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_FILE = PROJECT_ROOT / "config" / "settings.yaml"
ENV_FILE = PROJECT_ROOT / ".env"


class InsightFaceSettings(BaseSettings):
    model_name: str = "buffalo_l"
    device: str = "auto"
    cache_dir: Path = Path.home() / ".insightface" / "models"
    providers: Tuple[str, ...] = ()
    det_thresh: float = 0.5
    det_size: Tuple[int, int] = (640, 640)

    model_config = SettingsConfigDict(env_file=str(ENV_FILE), env_file_encoding="utf-8")


class IdentityDetectionSettings(BaseSettings):
    default_threshold: float = 0.45
    max_identities_per_image: int = Field(999, alias="max_faces_per_image")
    embedding_dimension: int = 1024
    max_candidates: int = 10

    model_config = SettingsConfigDict(env_file=str(ENV_FILE), env_file_encoding="utf-8")

    @property
    def max_faces_per_image(self) -> int:
        return self.max_identities_per_image


class RecognitionSettings(IdentityDetectionSettings):
    """Legacy alias exposed for backward compatibility."""


class IdentityClusteringSettings(BaseSettings):
    similarity_threshold: float = 0.6
    min_identity_cluster_size: int = Field(2, alias="min_cluster_size")
    max_identity_cluster_size: int = Field(1000, alias="max_cluster_size")

    model_config = SettingsConfigDict(env_file=str(ENV_FILE), env_file_encoding="utf-8")

    @property
    def min_cluster_size(self) -> int:
        return self.min_identity_cluster_size

    @property
    def max_cluster_size(self) -> int:
        return self.max_identity_cluster_size


class ClusteringSettings(IdentityClusteringSettings):
    """Legacy alias exposed for backward compatibility."""


class ThumbnailSettings(BaseSettings):
    storage_dir: Path = Path.home() / ".context-alt-text" / "thumbnails"
    base_url: str = "http://localhost:8000/thumbnails"
    size: int = 128
    padding_ratio: float = 0.15
    quality: int = 90

    model_config = SettingsConfigDict(env_file=str(ENV_FILE), env_file_encoding="utf-8")


@dataclass(frozen=True)
class RecognitionConfig:
    insightface: InsightFaceSettings
    identity_detection: IdentityDetectionSettings
    identity_clustering: IdentityClusteringSettings
    thumbnail: ThumbnailSettings

    @property
    def recognition(self) -> IdentityDetectionSettings:
        return self.identity_detection

    @property
    def clustering(self) -> IdentityClusteringSettings:
        return self.identity_clustering


def _load_yaml() -> dict[str, dict]:
    if not CONFIG_FILE.exists():
        return {}
    with CONFIG_FILE.open() as handle:
        return yaml.safe_load(handle) or {}


@lru_cache(maxsize=1)
def get_settings() -> RecognitionConfig:
    yaml_values = _load_yaml()

    insightface = InsightFaceSettings(**yaml_values.get("insightface", {}))

    identity_detection = IdentityDetectionSettings(
        **yaml_values.get("identity_detection", yaml_values.get("recognition", {}))
    )
    identity_clustering = IdentityClusteringSettings(**yaml_values.get("clustering", {}))
    thumbnail = ThumbnailSettings(**yaml_values.get("thumbnails", {}))

    return RecognitionConfig(
        insightface=insightface,
        identity_detection=identity_detection,
        identity_clustering=identity_clustering,
        thumbnail=thumbnail,
    )
