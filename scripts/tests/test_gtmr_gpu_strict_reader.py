"""G1 strict-reader causal REDs and custody counterexamples (GTMR GPU evidence contract v1).

Scope: authoring only. Every bundle is synthetic and written under pytest's ``tmp_path``. Nothing here
reaches a live GPU, database, OCI control plane, serving runtime, or credential, and no production
source is edited.

Labels (every test name carries exactly one):

* ``test_existing_baseline_*``  healthy control on the real existing call. Must pass.
* ``test_existing_control_*``   one-factor negative that the existing call already rejects. Must pass.
* ``test_existing_scope_*``     characterization of the lifecycle prerequisite's boundary. The strict layer
  owns these checks, so the existing call is pinned as it stands. Must pass.
* ``test_existing_red_*``       regression assertion on the existing approved receipt predicate.
  A failure blocks the union until the predicate's owning lane repairs it.
* ``test_proposal_*``           the future ``validate_strict_acceptance``. Each test has a strict
  expected failure for the absent c83 API; assertions remain active when the API exists.

Taxonomy used by the proposal tests (derived from the frozen contract; open to adjudication): an observed
contradiction (altered bytes, escape, extra artifact, stale window, wrong pin, CPU offload, cached GPU
output, non-idle STOP) is ``invalid`` (exit 2). A required join that is absent or reported missing is
``incomplete`` (exit 3). Only ``ready`` (exit 0) can pass. ``now`` is passed as an ISO-8601 string.

Proposed layout, adjudicable. The exporter refuses unrecognized entries in its own output directory
(``scripts/deploy/lib/export-gpu-evidence.sh:674``), so the sidecar and raw artifacts cannot share it::

    bundle_dir/
      strict-sidecar.json   collector metadata, artifacts[] and evidence sections
      raw/                  raw artifacts referenced by artifacts[] with sha256
      lifecycle/            exporter output, untouched; check_bundle(lifecycle/) is the prerequisite
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_CHECKER = REPO_ROOT / "scripts" / "gpu_burst_evidence.py"
EXISTING_FIXTURES = REPO_ROOT / "scripts" / "test_gpu_burst_evidence.py"
STRICT_MODULE = REPO_ROOT / "scripts" / "gpu_strict_acceptance.py"

RECEIPT_AT = "2026-09-01T00:20:00Z"  # inside the fixture RUNNING interval 00:10Z-00:30Z
PINNED_MODEL = "example-org/burst-model@rev-pinned"
OTHER_MODEL = "example-org/other-model@rev-other"
OTHER_INSTANCE = "ocid1.instance.other"
STOP_PRINCIPAL = "gpu-reaper"


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evidence = _load_module("gtmr_strict_reader_lifecycle_checker", EVIDENCE_CHECKER)
fixtures = _load_module("gtmr_strict_reader_burst_fixtures", EXISTING_FIXTURES)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pretty(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _canonical(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise TypeError(f"{path} must hold a JSON object")
    return loaded


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_bytes(_pretty(payload))


# ---- existing lifecycle checker: what the actual call does today ----


def _existing_verdict(bundle: Path) -> dict[str, Any]:
    return evidence.check_bundle(
        bundle, since=fixtures.SINCE, until=fixtures.UNTIL, expected_stop_principal=STOP_PRINCIPAL
    )


def _check(verdict: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    matches = [check for check in verdict["checks"] if check["name"] == name]
    assert len(matches) == 1, [check["name"] for check in verdict["checks"]]
    return matches[0]


def _assert_only_wp_predicate_can_differ(verdict: Mapping[str, Any]) -> None:
    failing = [
        check["name"] for check in verdict["checks"] if check["name"] != "wp_descriptions" and not check["passed"]
    ]
    assert failing == [], f"lifecycle checks must pass so only the WP predicate is under test: {failing}"


def _final_item(description: str, model_id: str = PINNED_MODEL, **provenance: object) -> dict[str, object]:
    return {
        "description": description,
        "generated_at": RECEIPT_AT,
        "tier": "final_gpu",
        "provenance": {"model_id": model_id, **provenance},
    }


def _receipts(*items: Mapping[str, object]) -> dict[str, object]:
    return {"items": [dict(item) for item in items]}


# ---- existing baseline: the healthy lifecycle bundle and the proposed layout ----


def test_existing_baseline_complete_lifecycle_bundle_passes(tmp_path: Path) -> None:
    bundle = fixtures._custom_bundle(tmp_path, receipts=_receipts(_final_item("a red bicycle beside a brick wall")))
    verdict = _existing_verdict(bundle)

    assert _check(verdict, "manifest_sha256")["passed"] is True
    assert _check(verdict, "wp_descriptions")["passed"] is True
    assert verdict["passed"] is True, verdict["failures"]


def test_existing_baseline_proposed_layout_keeps_lifecycle_prerequisite_green(tmp_path: Path) -> None:
    # The proposed layout places the untouched exporter output in lifecycle/. The existing
    # check_bundle must still pass there, and the raw artifacts must match their recorded digests.
    bundle, _policy = _build_strict(tmp_path)
    verdict = _existing_verdict(bundle / LIFECYCLE_DIR)

    assert verdict["passed"] is True, verdict["failures"]
    sidecar = _read_json(bundle / SIDECAR)
    for artifact in sidecar["artifacts"]:
        assert _digest((bundle / artifact["relative_path"]).read_bytes()) == artifact["sha256"]


# ---- existing controls: one-factor negatives the lifecycle prerequisite already rejects ----


def test_existing_control_altered_listed_bytes_fail_manifest_custody(tmp_path: Path) -> None:
    bundle = fixtures._custom_bundle(tmp_path, receipts=_receipts(_final_item("gpu description")))
    with (bundle / "wp_describe_receipts.json").open("ab") as handle:
        handle.write(b" ")
    check = _check(_existing_verdict(bundle), "manifest_sha256")

    assert check["passed"] is False
    assert "wp_describe_receipts.json" in check["detail"]


def test_existing_control_unlisted_extra_file_fails_closed(tmp_path: Path) -> None:
    bundle = fixtures._custom_bundle(tmp_path, receipts=_receipts(_final_item("gpu description")), extra_file=True)
    check = _check(_existing_verdict(bundle), "manifest_sha256")

    assert check["passed"] is False
    assert "unlisted.txt" in check["detail"]


def test_existing_control_manifest_path_escape_fails_closed(tmp_path: Path) -> None:
    bundle = fixtures._custom_bundle(tmp_path, receipts=_receipts(_final_item("gpu description")))
    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    manifest = _read_json(bundle / "manifest.json")
    manifest["files"].append(
        {
            "path": "../outside.json",
            "sha256": _digest(outside.read_bytes()),
            "command": "fixture",
            "capture_time": RECEIPT_AT,
        }
    )
    _write_json(bundle / "manifest.json", manifest)
    check = _check(_existing_verdict(bundle), "manifest_sha256")

    assert check["passed"] is False
    assert "../outside.json" in check["detail"]


def test_existing_control_missing_listed_artifact_fails_closed(tmp_path: Path) -> None:
    bundle = fixtures._custom_bundle(tmp_path, receipts=_receipts(_final_item("gpu description")))
    (bundle / "wp_describe_receipts.json").unlink()
    check = _check(_existing_verdict(bundle), "manifest_sha256")

    assert check["passed"] is False
    assert "wp_describe_receipts.json" in check["detail"]


def test_existing_control_instance_receipt_for_other_instance_fails(tmp_path: Path) -> None:
    bundle = fixtures._custom_bundle(
        tmp_path,
        receipts=_receipts(_final_item("gpu description")),
        instance={"data": {"id": OTHER_INSTANCE, "lifecycle-state": "STOPPED"}},
    )
    verdict = _existing_verdict(bundle)

    assert _check(verdict, "manifest_sha256")["passed"] is True
    assert _check(verdict, "instance_identity")["passed"] is False
    assert verdict["passed"] is False


def test_existing_control_two_identities_in_one_list_fail_the_predicate(tmp_path: Path) -> None:
    # Causal control for the sibling RED below: the same two identities, in one list, are rejected.
    mixed = _receipts(_final_item("first description", PINNED_MODEL), _final_item("second description", OTHER_MODEL))
    verdict = _existing_verdict(fixtures._custom_bundle(tmp_path, receipts=mixed))

    _assert_only_wp_predicate_can_differ(verdict)
    assert _check(verdict, "wp_descriptions")["passed"] is False


# ---- existing scope: prerequisite boundary, owned by the strict layer (pinned as it stands) ----


def test_existing_scope_entry_capture_time_is_not_freshness_checked(tmp_path: Path) -> None:
    # Entry-level capture_time is not evaluated by the prerequisite. Freshness is a strict-reader duty.
    bundle = fixtures._custom_bundle(tmp_path, receipts=_receipts(_final_item("gpu description")))
    manifest = _read_json(bundle / "manifest.json")
    for entry in manifest["files"]:
        entry["capture_time"] = "2020-01-01T00:00:00Z"
    _write_json(bundle / "manifest.json", manifest)
    verdict = _existing_verdict(bundle)

    assert _check(verdict, "capture_window")["passed"] is True
    assert verdict["passed"] is True, verdict["failures"]


def test_existing_scope_cached_final_gpu_receipt_passes_prerequisite(tmp_path: Path) -> None:
    # provenance.cached is emitted by the describe-run producer. The prerequisite does not read it.
    cached = _final_item("gpu description", cached=True)
    verdict = _existing_verdict(fixtures._custom_bundle(tmp_path, receipts=_receipts(cached)))

    assert _check(verdict, "wp_descriptions")["passed"] is True
    assert verdict["passed"] is True, verdict["failures"]


def test_existing_scope_consistent_unpinned_identity_passes_prerequisite(tmp_path: Path) -> None:
    # One consistent identity satisfies the prerequisite whether or not it is the operator's pin.
    unpinned = _final_item("gpu description", OTHER_MODEL)
    verdict = _existing_verdict(fixtures._custom_bundle(tmp_path, receipts=_receipts(unpinned)))

    assert _check(verdict, "wp_descriptions")["passed"] is True
    assert verdict["passed"] is True, verdict["failures"]


def test_existing_scope_tierless_receipt_without_lineage_passes_prerequisite(tmp_path: Path) -> None:
    # Legacy tierless receipts stay optional and count at the lifecycle level. The strict reader must not count them.
    legacy = {"items": [{"description": "one", "generated_at": RECEIPT_AT}]}
    verdict = _existing_verdict(fixtures._custom_bundle(tmp_path, receipts=legacy))

    assert _check(verdict, "wp_descriptions")["passed"] is True
    assert verdict["passed"] is True, verdict["failures"]


def test_existing_scope_sidecar_co_located_in_exporter_dir_is_unlisted(tmp_path: Path) -> None:
    # Composition constraint: a sidecar placed in the exporter directory is an unlisted file to the prerequisite.
    bundle, _policy = _build_strict(tmp_path)
    shutil.copy(bundle / SIDECAR, bundle / LIFECYCLE_DIR / SIDECAR)
    check = _check(_existing_verdict(bundle / LIFECYCLE_DIR), "manifest_sha256")

    assert check["passed"] is False
    assert SIDECAR in check["detail"]


# ---- existing causal RED: approved one-identity rule on the receipt predicate ----


def test_existing_red_second_identity_in_sibling_container_is_not_counted(tmp_path: Path) -> None:
    # Control: test_existing_control_two_identities_in_one_list_fail_the_predicate (same identities, one list).
    # One-factor delta: the second identity sits under the sibling key "data" instead of "items".
    # _receipt_items_report returns the first list-valued container it finds, so "data" is dropped unread.
    # The receipt is a robustness counterexample; the WordPress route emits one top-level items list today.
    sibling = {
        "items": [_final_item("first description", PINNED_MODEL)],
        "data": [_final_item("second description", OTHER_MODEL)],
    }
    verdict = _existing_verdict(fixtures._custom_bundle(tmp_path, receipts=sibling))

    _assert_only_wp_predicate_can_differ(verdict)
    wp = _check(verdict, "wp_descriptions")
    assert wp["passed"] is False, f"a second model identity was dropped unread and the predicate passed: {wp['detail']}"


# ============================================================================
# PROPOSAL: future validate_strict_acceptance(*, bundle_dir, policy, now).
# Each proposal below strictly expects only the absent c83 API failure.
# ============================================================================

Validate = Callable[..., Mapping[str, Any]]
EXIT_CODES = {"ready": 0, "incomplete": 3, "invalid": 2}

LIFECYCLE_DIR = "lifecycle"
RAW_DIR = "raw"
SIDECAR = "strict-sidecar.json"
LANE_ID = "feature-gtmr-red-gpu-strict-reader-20261-3d3739a1"
ENVIRONMENT = "fixture-env"
TENANT_ID = "tenant-fixture"
DATABASE_NAME = "alt_context_fixture"
DB_ROLE = "acx_fixture"
RUN_ID = "run-fixture-1"
MEDIA_ID = 42
OPERATION_ID = "op-fixture-1"
GENERATION = "gen-fixture-1"
PROMPT_VERSION = "prompt-fixture-v1"
MODEL_SHA256 = _digest(b"fixture-mapped-model-bytes")
PROJECTOR_SHA256 = _digest(b"fixture-projector-bytes")
IMAGE_SHA256 = _digest(b"fixture-submitted-image-bytes")
CONTEXT_SHA256 = _digest(b"fixture-canonical-context-json")
REQUEST_DIGEST = _digest(b"fixture-request")
CAPTURE_AT = "2026-09-01T00:31:00Z"
STALE_AT = "2026-08-31T23:00:00Z"
FUTURE_AT = "2026-09-01T03:00:00Z"
NOW = "2026-09-01T02:00:00Z"


class StrictAcceptanceNotImplementedError(RuntimeError):
    """The c83 strict acceptance entry point has not been implemented."""


@pytest.fixture
def validate() -> Validate:
    if not STRICT_MODULE.is_file():
        raise StrictAcceptanceNotImplementedError(
            "not implemented: C82R-HG3R-003 validate_strict_acceptance (c83)"
        )
    return _load_module("gtmr_gpu_strict_acceptance_proposal", STRICT_MODULE).validate_strict_acceptance


def _policy(lifecycle_manifest_sha256: str) -> dict[str, Any]:
    # Operator-selected expectations only. Producer output never supplies these values.
    return {
        "lane_id": LANE_ID,
        "environment": ENVIRONMENT,
        "tenant_id": TENANT_ID,
        "source_identity": "fixture-source-identity",
        "model_id": PINNED_MODEL,
        "model_sha256": MODEL_SHA256,
        "projector_sha256": PROJECTOR_SHA256,
        "image_sha256": IMAGE_SHA256,
        "context_sha256": CONTEXT_SHA256,
        "prompt_or_task_version": PROMPT_VERSION,
        "instance_id": fixtures.INSTANCE_ID,
        "stop_principal": STOP_PRINCIPAL,
        "database_name": DATABASE_NAME,
        "role": DB_ROLE,
        "lifecycle_manifest_sha256": lifecycle_manifest_sha256,
    }


def _payload(observations: list[dict[str, Any]]) -> dict[str, Any]:
    return {"observations": observations, "missing_reasons": []}


def _default_payloads() -> dict[str, dict[str, Any]]:
    # Raw producer output per evidence section. Each observation is copied into the sidecar with the raw digest.
    return {
        "demand": _payload(
            [
                {
                    "tenant_id": TENANT_ID,
                    "operation_id": OPERATION_ID,
                    "request_digest": REQUEST_DIGEST,
                    "accepted_at": "2026-09-01T00:09:00Z",
                    "state": "PERSISTED",
                    "expires_at": "2026-09-01T00:40:00Z",
                }
            ]
        ),
        "load": _payload(
            [
                {
                    "operation_id": OPERATION_ID,
                    "revision": 7,
                    "written_at": "2026-09-01T00:09:30Z",
                    "queue_depth": 1,
                    "in_flight": 0,
                    "batch_in_progress": False,
                    "lease_demand": 1,
                    "generation": GENERATION,
                }
            ]
        ),
        "output": _payload(
            [
                {
                    "tenant_id": TENANT_ID,
                    "run_id": RUN_ID,
                    "media_id": MEDIA_ID,
                    "status": "completed",
                    "tier": "final_gpu",
                    "result_generation": 3,
                    "generated_at": RECEIPT_AT,
                    "provenance": {
                        "model_id": PINNED_MODEL,
                        "cached": False,
                        "image_hash": IMAGE_SHA256,
                        "context_hash": CONTEXT_SHA256,
                        "prompt_or_task_version": PROMPT_VERSION,
                    },
                }
            ]
        ),
        "runtime": _payload(
            [
                {
                    "instance_id": fixtures.INSTANCE_ID,
                    "boot_id": "boot-fixture-1",
                    "container_id": "ctr-fixture-1",
                    "image_id": "img-fixture-1",
                    "gpu_uuid": "GPU-fixture-1",
                    "pid": 4242,
                    "process_start": "2026-09-01T00:10:05Z",
                    "mapped_model_sha256": MODEL_SHA256,
                    "projector_sha256": PROJECTOR_SHA256,
                    "offloaded_layers": 33,
                    "build": "build-fixture-1",
                    "request_id": "req-fixture-1",
                    "request_completed": True,
                }
            ]
        ),
        "pg": _payload(
            [
                {
                    "tenant_id": TENANT_ID,
                    "database_name": DATABASE_NAME,
                    "role": DB_ROLE,
                    "is_superuser": False,
                    "bypass_rls": False,
                    "rls_forced": True,
                    "committed_visible": True,
                    "foreign_tenant_rows": 0,
                }
            ]
        ),
        "stop": _payload(
            [
                {
                    "instance_id": fixtures.INSTANCE_ID,
                    "principal": STOP_PRINCIPAL,
                    "last_transition_reason": "idle",
                    "decision_consumed": True,
                    "consumed_generation": GENERATION,
                    "oci_final_state": "STOPPED",
                }
            ]
        ),
    }


def _artifact(relative: str, digest: str, at: str) -> dict[str, Any]:
    return {
        "relative_path": relative,
        "sha256": digest,
        "command_argv": ["fixture-collector", "<redacted>"],
        "exit_code": 0,
        "capture_started_at": at,
        "capture_finished_at": at,
    }


def _section(payload: Mapping[str, Any], digest: str) -> dict[str, Any]:
    return {
        "observations": [{**observation, "artifact_sha256": digest} for observation in payload["observations"]],
        "missing_reasons": list(payload["missing_reasons"]),
    }


def _build_strict(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    """Return a ready-shaped strict bundle and the operator policy that pins it. Every join is consistent."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    built = fixtures._custom_bundle(tmp_path, receipts=_receipts(_final_item("a red bicycle beside a brick wall")))
    bundle = tmp_path / "strict"
    bundle.mkdir()
    shutil.move(str(built), str(bundle / LIFECYCLE_DIR))
    (bundle / RAW_DIR).mkdir()
    artifacts: list[dict[str, Any]] = []
    sections: dict[str, Any] = {}
    for name, payload in _default_payloads().items():
        relative = f"{RAW_DIR}/{name}.json"
        raw = _pretty(payload)
        (bundle / relative).write_bytes(raw)
        digest = _digest(raw)
        artifacts.append(_artifact(relative, digest, CAPTURE_AT))
        sections[name] = _section(payload, digest)
    policy = _policy(_digest((bundle / LIFECYCLE_DIR / "manifest.json").read_bytes()))
    sidecar = {
        "schema_version": 1,
        "lane_id": LANE_ID,
        "environment": ENVIRONMENT,
        "selected_policy_sha256": _digest(_canonical(policy)),
        "artifacts": artifacts,
        "sections": sections,
    }
    _write_json(bundle / SIDECAR, sidecar)
    return bundle, policy


def _edit_sidecar(bundle: Path, mutate: Callable[[dict[str, Any]], object]) -> None:
    sidecar = _read_json(bundle / SIDECAR)
    mutate(sidecar)
    _write_json(bundle / SIDECAR, sidecar)


def _produce(bundle: Path, name: str, mutate: Callable[[dict[str, Any]], object]) -> None:
    """Producer-side change with intact custody: rewrite the raw artifact and re-reference its digest."""
    relative = f"{RAW_DIR}/{name}.json"
    payload = _read_json(bundle / relative)
    mutate(payload)
    raw = _pretty(payload)
    (bundle / relative).write_bytes(raw)
    digest = _digest(raw)

    def sync(sidecar: dict[str, Any]) -> None:
        for artifact in sidecar["artifacts"]:
            if artifact["relative_path"] == relative:
                artifact["sha256"] = digest
        sidecar["sections"][name] = _section(payload, digest)

    _edit_sidecar(bundle, sync)


def _drop_section(bundle: Path, name: str) -> None:
    relative = f"{RAW_DIR}/{name}.json"
    (bundle / relative).unlink()

    def remove(sidecar: dict[str, Any]) -> None:
        sidecar["sections"].pop(name)
        sidecar["artifacts"] = [artifact for artifact in sidecar["artifacts"] if artifact["relative_path"] != relative]

    _edit_sidecar(bundle, remove)


def _tamper_raw(bundle: Path, name: str) -> None:
    # Bytes change without a matching digest update: a custody break, not a producer change.
    path = bundle / RAW_DIR / f"{name}.json"
    path.write_bytes(path.read_bytes() + b" ")


def _run(validate: Validate, bundle: Path, policy: Mapping[str, Any]) -> Mapping[str, Any]:
    return validate(bundle_dir=bundle, policy=dict(policy), now=NOW)


def _assert_status(result: Mapping[str, Any], status: str) -> None:
    assert result["status"] == status, result
    assert result["exit_code"] == EXIT_CODES[status], result


def _output(payload: dict[str, Any]) -> dict[str, Any]:
    # First observation of the section. Used for output and runtime sections alike.
    return payload["observations"][0]


# ---- proposal: positive and status mapping ----


@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_positive_complete_bundle_is_ready",
)
def test_proposal_positive_complete_bundle_is_ready(validate: Validate, tmp_path: Path) -> None:
    bundle, policy = _build_strict(tmp_path)
    _assert_status(_run(validate, bundle, policy), "ready")


@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_status_maps_to_fixed_exit_codes",
)
def test_proposal_status_maps_to_fixed_exit_codes(validate: Validate, tmp_path: Path) -> None:
    ready, policy = _build_strict(tmp_path / "ready")
    _assert_status(_run(validate, ready, policy), "ready")

    incomplete, policy_incomplete = _build_strict(tmp_path / "incomplete")
    _drop_section(incomplete, "runtime")
    _assert_status(_run(validate, incomplete, policy_incomplete), "incomplete")

    invalid, policy_invalid = _build_strict(tmp_path / "invalid")
    _tamper_raw(invalid, "output")
    _assert_status(_run(validate, invalid, policy_invalid), "invalid")


@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_missing_sidecar_is_incomplete",
)
def test_proposal_missing_sidecar_is_incomplete(validate: Validate, tmp_path: Path) -> None:
    bundle, policy = _build_strict(tmp_path)
    (bundle / SIDECAR).unlink()
    _assert_status(_run(validate, bundle, policy), "incomplete")


@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_sidecar_schema_version_must_be_one",
)
def test_proposal_sidecar_schema_version_must_be_one(validate: Validate, tmp_path: Path) -> None:
    bundle, policy = _build_strict(tmp_path)
    _edit_sidecar(bundle, lambda sidecar: sidecar.update(schema_version=2))
    _assert_status(_run(validate, bundle, policy), "invalid")


@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_sidecar_artifact_entry_is_exact",
)
def test_proposal_sidecar_artifact_entry_is_exact(validate: Validate, tmp_path: Path) -> None:
    bundle, policy = _build_strict(tmp_path)
    _edit_sidecar(bundle, lambda sidecar: sidecar["artifacts"][0].pop("exit_code"))
    _assert_status(_run(validate, bundle, policy), "invalid")


# ---- proposal: custody (bytes, paths, extras, freshness, digests, policy and lane binding) ----


@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_altered_raw_bytes_are_invalid",
)
def test_proposal_altered_raw_bytes_are_invalid(validate: Validate, tmp_path: Path) -> None:
    bundle, policy = _build_strict(tmp_path)
    _tamper_raw(bundle, "output")
    _assert_status(_run(validate, bundle, policy), "invalid")


@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_missing_raw_artifact_is_incomplete",
)
def test_proposal_missing_raw_artifact_is_incomplete(validate: Validate, tmp_path: Path) -> None:
    bundle, policy = _build_strict(tmp_path)
    (bundle / RAW_DIR / "output.json").unlink()
    _assert_status(_run(validate, bundle, policy), "incomplete")


@pytest.mark.parametrize("stray", ["raw/stray.json", "lifecycle/stray.txt"])
@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_unreferenced_extra_file_is_invalid",
)
def test_proposal_unreferenced_extra_file_is_invalid(validate: Validate, tmp_path: Path, stray: str) -> None:
    bundle, policy = _build_strict(tmp_path)
    (bundle / stray).write_text("unexplained\n", encoding="utf-8")
    _assert_status(_run(validate, bundle, policy), "invalid")


@pytest.mark.parametrize("absolute", [False, True], ids=["relative-escape", "absolute-path"])
@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_artifact_path_escape_is_invalid",
)
def test_proposal_artifact_path_escape_is_invalid(validate: Validate, tmp_path: Path, absolute: bool) -> None:
    bundle, policy = _build_strict(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    relative = str(outside) if absolute else "../outside.json"
    _edit_sidecar(
        bundle,
        lambda sidecar: sidecar["artifacts"].append(_artifact(relative, _digest(outside.read_bytes()), CAPTURE_AT)),
    )
    _assert_status(_run(validate, bundle, policy), "invalid")


@pytest.mark.parametrize(
    "at", [pytest.param(STALE_AT, id="stale-before-window"), pytest.param(FUTURE_AT, id="future-after-now")]
)
@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_capture_outside_freshness_window_is_invalid",
)
def test_proposal_capture_outside_freshness_window_is_invalid(validate: Validate, tmp_path: Path, at: str) -> None:
    bundle, policy = _build_strict(tmp_path)

    def retime(sidecar: dict[str, Any]) -> None:
        for artifact in sidecar["artifacts"]:
            artifact["capture_started_at"] = at
            artifact["capture_finished_at"] = at

    _edit_sidecar(bundle, retime)
    _assert_status(_run(validate, bundle, policy), "invalid")


@pytest.mark.parametrize(("field", "value"), [("lane_id", "other-lane"), ("environment", "other-env")])
@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_sidecar_lane_or_environment_mismatch_is_invalid",
)
def test_proposal_sidecar_lane_or_environment_mismatch_is_invalid(
    validate: Validate, tmp_path: Path, field: str, value: str
) -> None:
    bundle, policy = _build_strict(tmp_path)
    _edit_sidecar(bundle, lambda sidecar: sidecar.update({field: value}))
    _assert_status(_run(validate, bundle, policy), "invalid")


@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_substituted_policy_is_invalid",
)
def test_proposal_substituted_policy_is_invalid(validate: Validate, tmp_path: Path) -> None:
    bundle, policy = _build_strict(tmp_path)
    substituted = {**policy, "model_id": OTHER_MODEL}
    _assert_status(_run(validate, bundle, substituted), "invalid")


@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_lifecycle_manifest_bytes_must_match_retained_digest",
)
def test_proposal_lifecycle_manifest_bytes_must_match_retained_digest(validate: Validate, tmp_path: Path) -> None:
    # The exporter manifest's listed files still verify. Only the externally retained manifest digest breaks.
    bundle, policy = _build_strict(tmp_path)
    manifest = bundle / LIFECYCLE_DIR / "manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b"\n")
    _assert_status(_run(validate, bundle, policy), "invalid")


# ---- proposal: strict predicate (cache, identity, tier, runtime, load, stop, pg) ----


@pytest.mark.parametrize(
    ("mutate", "status"),
    [
        pytest.param(lambda p: _output(p)["provenance"].update(cached=True), "invalid", id="cached-true"),
        pytest.param(lambda p: _output(p)["provenance"].update(cached="no"), "invalid", id="cached-nonboolean"),
        pytest.param(lambda p: _output(p)["provenance"].pop("cached"), "incomplete", id="cached-absent"),
    ],
)
@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_cache_state_must_be_explicit_and_uncached",
)
def test_proposal_cache_state_must_be_explicit_and_uncached(
    validate: Validate, tmp_path: Path, mutate: Callable[[dict[str, Any]], object], status: str
) -> None:
    bundle, policy = _build_strict(tmp_path)
    _produce(bundle, "output", mutate)
    _assert_status(_run(validate, bundle, policy), status)


@pytest.mark.parametrize(
    ("mutate", "status"),
    [
        pytest.param(lambda p: _output(p).update(tier="provisional_cpu"), "invalid", id="cpu-tier"),
        pytest.param(lambda p: _output(p).pop("tier"), "incomplete", id="tier-absent"),
    ],
)
@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_output_tier_must_be_final_gpu",
)
def test_proposal_output_tier_must_be_final_gpu(
    validate: Validate, tmp_path: Path, mutate: Callable[[dict[str, Any]], object], status: str
) -> None:
    bundle, policy = _build_strict(tmp_path)
    _produce(bundle, "output", mutate)
    _assert_status(_run(validate, bundle, policy), status)


@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_output_identity_must_equal_operator_pin",
)
def test_proposal_output_identity_must_equal_operator_pin(validate: Validate, tmp_path: Path) -> None:
    # Consistent but arbitrary identity: one identity across receipts is not enough, it must be the pin.
    bundle, policy = _build_strict(tmp_path)
    _produce(bundle, "output", lambda p: _output(p)["provenance"].update(model_id=OTHER_MODEL))
    _assert_status(_run(validate, bundle, policy), "invalid")


@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_mixed_output_identities_are_invalid",
)
def test_proposal_mixed_output_identities_are_invalid(validate: Validate, tmp_path: Path) -> None:
    bundle, policy = _build_strict(tmp_path)

    def add_other(payload: dict[str, Any]) -> None:
        extra = {**_output(payload), "media_id": MEDIA_ID + 1}
        extra["provenance"] = {**extra["provenance"], "model_id": OTHER_MODEL}
        payload["observations"].append(extra)

    _produce(bundle, "output", add_other)
    _assert_status(_run(validate, bundle, policy), "invalid")


@pytest.mark.parametrize("key", ["image_hash", "context_hash", "prompt_or_task_version"])
@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_input_and_prompt_pins_must_match",
)
def test_proposal_input_and_prompt_pins_must_match(validate: Validate, tmp_path: Path, key: str) -> None:
    bundle, policy = _build_strict(tmp_path)
    _produce(bundle, "output", lambda p: _output(p)["provenance"].update({key: _digest(b"changed")}))
    _assert_status(_run(validate, bundle, policy), "invalid")


@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_cpu_offload_is_invalid",
)
def test_proposal_cpu_offload_is_invalid(validate: Validate, tmp_path: Path) -> None:
    bundle, policy = _build_strict(tmp_path)
    _produce(bundle, "runtime", lambda p: _output(p).update(offloaded_layers=0))
    _assert_status(_run(validate, bundle, policy), "invalid")


@pytest.mark.parametrize("key", ["mapped_model_sha256", "projector_sha256"])
@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_wrong_model_or_projector_is_invalid",
)
def test_proposal_wrong_model_or_projector_is_invalid(validate: Validate, tmp_path: Path, key: str) -> None:
    bundle, policy = _build_strict(tmp_path)
    _produce(bundle, "runtime", lambda p: _output(p).update({key: _digest(b"swapped")}))
    _assert_status(_run(validate, bundle, policy), "invalid")


@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_runtime_instance_must_match_policy_pin",
)
def test_proposal_runtime_instance_must_match_policy_pin(validate: Validate, tmp_path: Path) -> None:
    bundle, policy = _build_strict(tmp_path)
    _produce(bundle, "runtime", lambda p: _output(p).update(instance_id=OTHER_INSTANCE))
    _assert_status(_run(validate, bundle, policy), "invalid")


@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_config_pins_and_gpu_utilization_cannot_prove_runtime",
)
def test_proposal_config_pins_and_gpu_utilization_cannot_prove_runtime(validate: Validate, tmp_path: Path) -> None:
    # Configured pins, /v1/models, and GPU utilization are not the observed loaded process or mapping.
    bundle, policy = _build_strict(tmp_path)
    _produce(
        bundle,
        "runtime",
        lambda p: p.update(
            observations=[
                {
                    "config_pins": {"model_id": PINNED_MODEL},
                    "v1_models": [PINNED_MODEL],
                    "nvidia_smi_utilization_percent": 97,
                }
            ]
        ),
    )
    _assert_status(_run(validate, bundle, policy), "incomplete")


@pytest.mark.parametrize("section", ["demand", "output", "runtime", "load", "pg", "stop"])
@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_absent_evidence_section_is_incomplete",
)
def test_proposal_absent_evidence_section_is_incomplete(validate: Validate, tmp_path: Path, section: str) -> None:
    bundle, policy = _build_strict(tmp_path)
    _drop_section(bundle, section)
    _assert_status(_run(validate, bundle, policy), "incomplete")


@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_section_reporting_missing_evidence_is_incomplete_not_invalid",
)
def test_proposal_section_reporting_missing_evidence_is_incomplete_not_invalid(
    validate: Validate, tmp_path: Path
) -> None:
    # Producers may emit incomplete evidence. A reported gap is absence, not a contradiction.
    bundle, policy = _build_strict(tmp_path)

    def report_gap(payload: dict[str, Any]) -> None:
        payload["observations"] = []
        payload["missing_reasons"] = ["database connection timed out"]

    _produce(bundle, "pg", report_gap)
    _assert_status(_run(validate, bundle, policy), "incomplete")


@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_observation_without_raw_digest_is_incomplete",
)
def test_proposal_observation_without_raw_digest_is_incomplete(validate: Validate, tmp_path: Path) -> None:
    bundle, policy = _build_strict(tmp_path)
    _edit_sidecar(bundle, lambda sidecar: sidecar["sections"]["runtime"]["observations"][0].pop("artifact_sha256"))
    _assert_status(_run(validate, bundle, policy), "incomplete")


@pytest.mark.parametrize(
    ("mutate", "status"),
    [
        pytest.param(lambda p: p["observations"][0].pop("operation_id"), "incomplete", id="load-unlinked"),
        pytest.param(
            lambda p: p["observations"][0].update(operation_id="op-preexisting"), "invalid", id="other-operation"
        ),
    ],
)
@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_load_revision_must_attribute_to_this_operation",
)
def test_proposal_load_revision_must_attribute_to_this_operation(
    validate: Validate, tmp_path: Path, mutate: Callable[[dict[str, Any]], object], status: str
) -> None:
    bundle, policy = _build_strict(tmp_path)
    _produce(bundle, "load", mutate)
    _assert_status(_run(validate, bundle, policy), status)


@pytest.mark.parametrize(
    ("mutate", "status"),
    [
        pytest.param(
            lambda p: p["observations"][0].update(last_transition_reason="emergency_finally"),
            "invalid",
            id="emergency-stop",
        ),
        pytest.param(
            lambda p: p["observations"][0].update(principal="human-operator"), "invalid", id="wrong-principal"
        ),
        pytest.param(
            lambda p: p["observations"][0].update(decision_consumed=False), "incomplete", id="decision-unconsumed"
        ),
    ],
)
@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_idle_stop_requires_consumed_decision_and_expected_principal",
)
def test_proposal_idle_stop_requires_consumed_decision_and_expected_principal(
    validate: Validate, tmp_path: Path, mutate: Callable[[dict[str, Any]], object], status: str
) -> None:
    bundle, policy = _build_strict(tmp_path)
    _produce(bundle, "stop", mutate)
    _assert_status(_run(validate, bundle, policy), status)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda p: p["observations"][0].update(is_superuser=True), id="superuser"),
        pytest.param(lambda p: p["observations"][0].update(bypass_rls=True), id="bypassrls"),
        pytest.param(lambda p: p["observations"][0].update(rls_forced=False), id="force-rls-disabled"),
        pytest.param(lambda p: p["observations"][0].update(committed_visible=False), id="uncommitted-only"),
        pytest.param(lambda p: p["observations"][0].update(foreign_tenant_rows=3), id="foreign-tenant-rows"),
        pytest.param(lambda p: p["observations"][0].update(database_name="alt_context_other"), id="wrong-database"),
    ],
)
@pytest.mark.xfail(
    not STRICT_MODULE.is_file(),
    strict=True,
    raises=StrictAcceptanceNotImplementedError,
    reason="not implemented: C82R-HG3R-003 test_proposal_restricted_pg_observation_refuses_unsafe_role_or_visibility",
)
def test_proposal_restricted_pg_observation_refuses_unsafe_role_or_visibility(
    validate: Validate, tmp_path: Path, mutate: Callable[[dict[str, Any]], object]
) -> None:
    bundle, policy = _build_strict(tmp_path)
    _produce(bundle, "pg", mutate)
    _assert_status(_run(validate, bundle, policy), "invalid")
