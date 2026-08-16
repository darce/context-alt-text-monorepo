"""Load and validate the stack-pair config against the FIR23-STACK table (rg-008)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

PINNED_PRIMARY_ENDPOINT = "detection_recall@frame_e2e/label_map_primary"

LEGAL_METRICS = (
    "detection_recall",
    "detection_precision",
    "identification_recall",
    "identification_precision",
)
LEGAL_FRAMES = ("frame_e2e", "frame_fir5_native")
LEGAL_LABEL_MAPS = ("label_map_primary", "label_map_optimistic")
LEGAL_ENDPOINTS: frozenset[str] = frozenset(
    f"{metric}@{frame}/{label}"
    for metric in LEGAL_METRICS
    for frame in LEGAL_FRAMES
    for label in LEGAL_LABEL_MAPS
)

ROOT_KEYS = frozenset(
    {
        "wall_clock_timeout_sec",
        "job_poll_timeout_sec",
        "item_max_attempts",
        "accepted_set_floor",
        "max_differential_attrition",
        "allow_private_source",
        "images_dir",
        "manifest_sha256",
        "baseline_manifest_path",
        "media_url_map_path",
        "head_to_head_delta",
        "bootstrap_seed",
        "primary_endpoint",
        "secondary_endpoints",
        "stacks",
    }
)
STACK_KEYS = frozenset(
    {
        "stack_id",
        "role",
        "base_url",
        "expected_profile",
        "expected_pgvector_dim",
        "opencv_major",
        "api_key_env",
        "tenant_id_env",
    }
)
DEPLOY_OWNERSHIP_KEYS = frozenset(
    {
        "compose_project",
        "network",
        "volume_path",
        "volumes",
        "image_tag",
        "image",
        "caddyfile",
        "systemd_unit",
        "db_volume",
        "secret_rotation",
    }
)

FIR23_STACK_ALLOWLIST: dict[str, dict[str, Any]] = {
    "acx-dev-insightface": {
        "role": "insightface_judge",
        "expected_profile": "insightface",
        "expected_pgvector_dim": 512,
        "hosts": frozenset({"dev.api.altcontext.com"}),
    },
    "acx-dev-fir": {
        "role": "face_pipeline_candidate",
        "expected_profile": "face_pipeline",
        "expected_pgvector_dim": 128,
        "hosts": frozenset({"fir.api.altcontext.com"}),
    },
}

REQUIRED_ROOT_KEYS = frozenset(
    {
        "head_to_head_delta",
        "bootstrap_seed",
        "primary_endpoint",
        "secondary_endpoints",
        "stacks",
    }
)
REQUIRED_STACK_KEYS = STACK_KEYS


class BenchError(Exception):
    """Stable-code bench failure."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class StackEndpoint:
    stack_id: str
    role: str
    base_url: str
    expected_profile: str
    expected_pgvector_dim: int
    opencv_major: int | None
    api_key_env: str
    tenant_id_env: str


@dataclass(frozen=True)
class StackPairConfig:
    stacks: tuple[StackEndpoint, ...]
    head_to_head_delta: float
    bootstrap_seed: int
    primary_endpoint: str
    secondary_endpoints: tuple[str, ...]
    wall_clock_timeout_sec: int = 3600
    job_poll_timeout_sec: int = 600
    item_max_attempts: int = 2
    accepted_set_floor: float | int = 0.90
    max_differential_attrition: float = 0.05
    allow_private_source: bool = False
    images_dir: str | None = None
    manifest_sha256: str | None = None
    baseline_manifest_path: str | None = None
    media_url_map_path: str | None = None

    def endpoint(self, stack_id: str) -> StackEndpoint:
        for stack in self.stacks:
            if stack.stack_id == stack_id:
                return stack
        raise BenchError("unknown_stack_id", f"stack_id {stack_id!r} is not in this pair")

    @property
    def allowlist_ids(self) -> frozenset[str]:
        return frozenset(stack.stack_id for stack in self.stacks)


def load_stack_pair(path: str | Path) -> StackPairConfig:
    raw_path = Path(path)
    text = raw_path.read_text(encoding="utf-8")
    if raw_path.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise BenchError("config_invalid", "stack-pair config must be a mapping")
    _reject_deploy_keys(data, where="root")
    unknown = set(data) - ROOT_KEYS
    if unknown:
        raise BenchError("unknown_config_key", f"unknown root keys: {sorted(unknown)}")
    missing = REQUIRED_ROOT_KEYS - set(data)
    if missing:
        raise BenchError("missing_required_key", f"missing required keys: {sorted(missing)}")

    stacks_raw = data["stacks"]
    if not isinstance(stacks_raw, list) or len(stacks_raw) != 2:
        raise BenchError("config_invalid", "stacks must be a list of exactly two entries")

    endpoints = tuple(_parse_stack(entry) for entry in stacks_raw)
    ids = [e.stack_id for e in endpoints]
    if len(set(ids)) != 2:
        raise BenchError("config_invalid", "stack_id values must be unique")

    primary = data["primary_endpoint"]
    secondaries = data["secondary_endpoints"]
    _validate_endpoints(primary, secondaries)

    return StackPairConfig(
        stacks=endpoints,
        head_to_head_delta=_as_float(data["head_to_head_delta"], "head_to_head_delta"),
        bootstrap_seed=_as_int(data["bootstrap_seed"], "bootstrap_seed"),
        primary_endpoint=primary,
        secondary_endpoints=tuple(secondaries),
        wall_clock_timeout_sec=int(data.get("wall_clock_timeout_sec", 3600)),
        job_poll_timeout_sec=int(data.get("job_poll_timeout_sec", 600)),
        item_max_attempts=int(data.get("item_max_attempts", 2)),
        accepted_set_floor=_validate_floor(data.get("accepted_set_floor", 0.90)),
        max_differential_attrition=_validate_attrition(data.get("max_differential_attrition", 0.05)),
        allow_private_source=bool(data.get("allow_private_source", False)),
        images_dir=data.get("images_dir"),
        manifest_sha256=data.get("manifest_sha256"),
        baseline_manifest_path=data.get("baseline_manifest_path"),
        media_url_map_path=data.get("media_url_map_path"),
    )


def _reject_deploy_keys(mapping: dict[str, Any], *, where: str) -> None:
    hit = DEPLOY_OWNERSHIP_KEYS & set(mapping)
    if hit:
        raise BenchError(
            "deploy_ownership_key_rejected",
            f"deploy-ownership key(s) {sorted(hit)} at {where} are FIR23-STACK-owned",
        )


def _parse_stack(entry: Any) -> StackEndpoint:
    if not isinstance(entry, dict):
        raise BenchError("config_invalid", "each stack entry must be a mapping")
    _reject_deploy_keys(entry, where="stack")
    unknown = set(entry) - STACK_KEYS
    if unknown:
        raise BenchError("unknown_config_key", f"unknown stack keys: {sorted(unknown)}")
    if "opencv_major" not in entry:
        raise BenchError("opencv_major_unattested", "stack entry missing opencv_major")
    missing = REQUIRED_STACK_KEYS - set(entry)
    if missing:
        if "opencv_major" in missing:
            raise BenchError("opencv_major_unattested", "stack entry missing opencv_major")
        raise BenchError("missing_required_key", f"stack missing keys: {sorted(missing)}")

    try:
        opencv_major = int(entry["opencv_major"])
    except (TypeError, ValueError) as exc:
        raise BenchError("opencv_major_unattested", "opencv_major is not a parseable integer") from exc

    stack_id = str(entry["stack_id"])
    if stack_id not in FIR23_STACK_ALLOWLIST:
        raise BenchError("unknown_stack_id", f"stack_id {stack_id!r} is not in FIR23_STACK_ALLOWLIST")
    spec = FIR23_STACK_ALLOWLIST[stack_id]
    role = str(entry["role"])
    if role != spec["role"]:
        raise BenchError("config_invalid", f"role {role!r} does not match allowlist for {stack_id}")
    profile = str(entry["expected_profile"])
    if profile != spec["expected_profile"]:
        raise BenchError("config_invalid", f"expected_profile {profile!r} does not match {stack_id}")
    dim = _as_int(entry["expected_pgvector_dim"], "expected_pgvector_dim")
    if dim != spec["expected_pgvector_dim"]:
        raise BenchError("config_invalid", f"expected_pgvector_dim {dim} does not match {stack_id}")

    base_url = _normalize_base_url(str(entry["base_url"]))
    host = urlparse(base_url).hostname or ""
    if host.lower() not in spec["hosts"]:
        raise BenchError("base_url_not_allowlisted", f"base_url host {host!r} is not allowlisted for {stack_id}")

    return StackEndpoint(
        stack_id=stack_id,
        role=role,
        base_url=base_url,
        expected_profile=profile,
        expected_pgvector_dim=dim,
        opencv_major=opencv_major,
        api_key_env=str(entry["api_key_env"]),
        tenant_id_env=str(entry["tenant_id_env"]),
    )


def _normalize_base_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise BenchError("base_url_invalid", f"base_url {url!r} must be absolute http(s)")
    if parsed.query or parsed.fragment:
        raise BenchError("base_url_invalid", f"base_url {url!r} must not include query or fragment")
    path = parsed.path or ""
    if path not in {"", "/"}:
        raise BenchError("base_url_invalid", f"base_url {url!r} must not include a path")
    return f"{parsed.scheme}://{parsed.netloc}"


def _validate_endpoints(primary: Any, secondaries: Any) -> None:
    if not isinstance(primary, str) or primary != PINNED_PRIMARY_ENDPOINT:
        raise BenchError(
            "config_endpoint_invalid",
            f"primary_endpoint must be {PINNED_PRIMARY_ENDPOINT!r}",
        )
    if not isinstance(secondaries, list):
        raise BenchError("config_endpoint_invalid", "secondary_endpoints must be a list")
    seen: set[str] = set()
    for item in secondaries:
        if not isinstance(item, str) or item not in LEGAL_ENDPOINTS or item == primary:
            raise BenchError("config_endpoint_invalid", f"illegal secondary endpoint {item!r}")
        if item in seen:
            raise BenchError("config_endpoint_invalid", f"duplicate secondary endpoint {item!r}")
        seen.add(item)


def _validate_floor(value: Any) -> float | int:
    if isinstance(value, bool):
        raise BenchError(
            "accepted_set_floor_invalid",
            "accepted_set_floor must be float in (0, 1) or int >= 2",
        )
    if isinstance(value, int):
        if value == 1:
            raise BenchError(
                "accepted_set_floor_invalid",
                "accepted_set_floor must be float in (0, 1) or int >= 2; got 1",
            )
        if value < 2:
            raise BenchError(
                "accepted_set_floor_invalid",
                "accepted_set_floor must be float in (0, 1) or int >= 2",
            )
        return value
    if isinstance(value, float):
        if value == 1.0:
            raise BenchError(
                "accepted_set_floor_invalid",
                "accepted_set_floor must be float in (0, 1) or int >= 2; got 1",
            )
        if not (0.0 < value < 1.0):
            raise BenchError(
                "accepted_set_floor_invalid",
                "accepted_set_floor must be float in (0, 1) or int >= 2",
            )
        return value
    raise BenchError(
        "accepted_set_floor_invalid",
        "accepted_set_floor must be float in (0, 1) or int >= 2",
    )


def _validate_attrition(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise BenchError("max_differential_attrition_invalid", "max_differential_attrition must be a float") from exc
    if parsed < 0.0 or parsed > 1.0:
        raise BenchError("max_differential_attrition_invalid", "max_differential_attrition must be in [0.0, 1.0]")
    return parsed


def _as_float(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise BenchError("config_invalid", f"{name} must be numeric") from exc


def _as_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        try:
            if isinstance(value, bool):
                raise ValueError
            return int(value)
        except (TypeError, ValueError) as exc:
            raise BenchError("config_invalid", f"{name} must be an integer") from exc
    return value
