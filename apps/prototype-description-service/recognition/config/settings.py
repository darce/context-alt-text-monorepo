"""Settings loader for the recognition subsystem."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Tuple

import yaml
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


class RecognitionSettings(BaseSettings):
    default_threshold: float = 0.45
    max_faces_per_image: int = 999
    embedding_dimension: int = 1024
    max_candidates: int = 10

    model_config = SettingsConfigDict(env_file=str(ENV_FILE), env_file_encoding="utf-8")


class ClusteringSettings(BaseSettings):
    similarity_threshold: float = 0.6
    min_cluster_size: int = 2
    max_cluster_size: int = 1000

    model_config = SettingsConfigDict(env_file=str(ENV_FILE), env_file_encoding="utf-8")


@dataclass(frozen=True)
class RecognitionConfig:
    insightface: InsightFaceSettings
    recognition: RecognitionSettings
    clustering: ClusteringSettings


def _load_yaml() -> dict[str, dict]:
    if not CONFIG_FILE.exists():
        return {}
    with CONFIG_FILE.open() as handle:
        return yaml.safe_load(handle) or {}


@lru_cache(maxsize=1)
def get_settings() -> RecognitionConfig:
    yaml_values = _load_yaml()

    insightface = InsightFaceSettings(**yaml_values.get("insightface", {}))
    recognition = RecognitionSettings(**yaml_values.get("recognition", {}))
    clustering = ClusteringSettings(**yaml_values.get("clustering", {}))

    return RecognitionConfig(
        insightface=insightface,
        recognition=recognition,
        clustering=clustering,
    )
