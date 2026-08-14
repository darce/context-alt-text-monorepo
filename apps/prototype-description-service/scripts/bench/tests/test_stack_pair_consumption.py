"""Stack-pair loader: consumption table, deploy-ownership reject, floor forms."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.bench.stack_pair import (
    DEPLOY_OWNERSHIP_KEYS,
    BenchError,
    load_stack_pair,
)
from scripts.bench.tests.conftest import FIR_STACK, INSIGHTFACE_STACK, valid_pair_dict, write_pair

PRIMARY = "detection_recall@frame_e2e/label_map_primary"


def _load(tmp_path: Path, **overrides: object):
    return load_stack_pair(write_pair(tmp_path / "pair.yaml", valid_pair_dict(**overrides)))


def test_valid_pair_loads(tmp_path: Path) -> None:
    pair = _load(tmp_path)
    assert {s.stack_id for s in pair.stacks} == {"acx-dev-insightface", "acx-dev-fir"}


def test_unknown_stack_id_fails(tmp_path: Path) -> None:
    stacks = [dict(INSIGHTFACE_STACK), dict(FIR_STACK)]
    stacks[0]["stack_id"] = "acx-prod-something"
    with pytest.raises(BenchError) as exc:
        _load(tmp_path, stacks=stacks)
    assert exc.value.code == "unknown_stack_id"


def test_unknown_base_url_fails(tmp_path: Path) -> None:
    stacks = [dict(INSIGHTFACE_STACK), dict(FIR_STACK)]
    stacks[0]["base_url"] = "https://evil.example.com"
    with pytest.raises(BenchError) as exc:
        _load(tmp_path, stacks=stacks)
    assert exc.value.code == "base_url_not_allowlisted"


@pytest.mark.parametrize("key", sorted(DEPLOY_OWNERSHIP_KEYS))
def test_deploy_ownership_key_rejected(tmp_path: Path, key: str) -> None:
    payload = valid_pair_dict()
    payload[key] = "nope"
    with pytest.raises(BenchError) as exc:
        load_stack_pair(write_pair(tmp_path / f"{key}.yaml", payload))
    assert exc.value.code == "deploy_ownership_key_rejected"


def test_allowed_key_control_still_loads(tmp_path: Path) -> None:
    pair = _load(tmp_path, images_dir="/tmp/corpus")
    assert pair.images_dir == "/tmp/corpus"


@pytest.mark.parametrize("value", [1, 1.0, 1.5, -1, "ninety"])
def test_floor_forms_rejected(tmp_path: Path, value: object) -> None:
    with pytest.raises(BenchError) as exc:
        _load(tmp_path, accepted_set_floor=value)
    assert exc.value.code == "accepted_set_floor_invalid"


def test_base_url_with_path_rejected(tmp_path: Path) -> None:
    stacks = [dict(INSIGHTFACE_STACK), dict(FIR_STACK)]
    stacks[0]["base_url"] = "https://dev.api.altcontext.com/v1"
    with pytest.raises(BenchError) as exc:
        _load(tmp_path, stacks=stacks)
    assert exc.value.code == "base_url_invalid"


@pytest.mark.parametrize("value", [0.9, 2])
def test_floor_forms_accepted(tmp_path: Path, value: object) -> None:
    pair = _load(tmp_path, accepted_set_floor=value)
    assert pair.accepted_set_floor == value


@pytest.mark.parametrize("missing", ["bootstrap_seed", "head_to_head_delta", "primary_endpoint", "secondary_endpoints"])
def test_missing_required_stat_keys_fail(tmp_path: Path, missing: str) -> None:
    payload = valid_pair_dict()
    del payload[missing]
    with pytest.raises(BenchError) as exc:
        load_stack_pair(write_pair(tmp_path / f"miss-{missing}.yaml", payload))
    assert exc.value.code == "missing_required_key"


def test_wrong_primary_endpoint_invalid(tmp_path: Path) -> None:
    with pytest.raises(BenchError) as exc:
        _load(tmp_path, primary_endpoint="identification_recall@frame_e2e/label_map_primary")
    assert exc.value.code == "config_endpoint_invalid"


def test_unknown_root_key_rejected(tmp_path: Path) -> None:
    payload = valid_pair_dict()
    payload["compose_not_this"] = True
    # unknown key that is not a deploy-ownership name
    payload["not_a_real_key"] = 1
    with pytest.raises(BenchError) as exc:
        load_stack_pair(write_pair(tmp_path / "unk.yaml", payload))
    assert exc.value.code == "unknown_config_key"
