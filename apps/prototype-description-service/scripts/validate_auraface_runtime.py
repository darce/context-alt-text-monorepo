"""AuraFace acceptance entrypoint: offline, fail-closed, and digest-only.

``validate_aura_acceptance`` composes the shared closed boundary, target/store gate,
and loaded-runtime gate. Explicit Aura acceptance admits the identity-only blob ownership
repair role while API/worker retain the complete runtime schema. Present contradictions
outrank incomplete observations; gate order breaks ties. The shared validator's default
and FIR128 behavior remain strict. No missing observation is filled from a policy pin.

Outcomes: ``ready`` (exit 0), ``incomplete`` (exit 1), ``invalid`` (exit 2). These match the FIR
validator and the frozen Aura acceptance tests. Reports are digest-only: raw snapshot, sidecar, and
policy content are never printed.

Offline CLI. Every input is a JSON file except ``--now``. The CLI performs no live action::

    python -m scripts.validate_auraface_runtime --snapshot S.json --freshness-policy F.json \\
        --isolation-policy I.json --aura-evidence E.json --acceptance-policy A.json \\
        --now 2026-09-20T12:01:00Z
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from scripts import aura_target_store_gate
from scripts.validate_fir_dev_runtime import _contains_secret_shaped, validate_snapshot

ENTRYPOINT_CONTRACT = "candidate512"
EVIDENCE_ROLES: tuple[str, ...] = ("api", "worker")
_EXIT_CODES: dict[str, int] = {"ready": 0, "incomplete": 1, "invalid": 2}


def validate_aura_acceptance(
    snapshot: Mapping[str, Any],
    *,
    aura_evidence: Mapping[str, Any],
    freshness_policy: Mapping[str, Any],
    isolation_policy: Mapping[str, Any],
    acceptance_policy: Mapping[str, Any],
    now: Any,
) -> dict[str, Any]:
    """Return the acceptance outcome for one Aura target. The result carries status, exit code, reason, and report."""

    if any(_contains_secret_shaped(value) for value in (aura_evidence, isolation_policy, acceptance_policy)):
        return _outcome("invalid", "secret_shaped_input", "input", snapshot, aura_evidence, acceptance_policy)

    findings: list[tuple[str, str, str]] = []
    presence = _evidence_presence_reason(aura_evidence)
    if presence is not None:
        findings.append(("incomplete", presence, "evidence"))
    missing = aura_target_store_gate.missing_evidence_reason(snapshot)
    if missing is not None:
        findings.append(("incomplete", missing, "evidence"))

    shared = validate_snapshot(
        snapshot,
        freshness_policy=freshness_policy,
        isolation_policy=isolation_policy,
        now=now,
        contract=ENTRYPOINT_CONTRACT,
        aura_acceptance=True,
    )
    if shared["status"] == "invalid":
        return _outcome("invalid", shared["reason_code"], "shared", snapshot, aura_evidence, acceptance_policy)
    elif shared["status"] == "incomplete":
        findings.append(("incomplete", shared["reason_code"], "shared"))

    target = aura_target_store_gate.validate_target_store(
        snapshot,
        isolation_policy=isolation_policy,
        acceptance_policy=acceptance_policy,
    )
    if target is not None:
        findings.append((*target, "target"))

    from scripts.aura_loaded_runtime_gate import validate_loaded_runtime

    runtime = validate_loaded_runtime(snapshot, aura_evidence=aura_evidence, acceptance_policy=acceptance_policy)
    if runtime is not None:
        findings.append((*runtime, "runtime"))
    # Gate order breaks ties; present contradictions outrank missing observations.
    for status in ("invalid", "incomplete"):
        for finding_status, reason, stage in findings:
            if finding_status == status:
                return _outcome(status, reason, stage, snapshot, aura_evidence, acceptance_policy)
    return _outcome("ready", "ready", "ready", snapshot, aura_evidence, acceptance_policy)


def _evidence_presence_reason(aura_evidence: Any) -> str | None:
    roles = aura_evidence.get("runtime_roles") if isinstance(aura_evidence, Mapping) else None
    if not isinstance(roles, Mapping) or any(not isinstance(roles.get(role), Mapping) for role in EVIDENCE_ROLES):
        return "incomplete_aura_evidence"
    return None


def _digest(value: Any) -> str | None:
    try:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return None
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _outcome(
    status: str,
    reason_code: str,
    stage: str,
    snapshot: Any,
    aura_evidence: Any,
    acceptance_policy: Any,
) -> dict[str, Any]:
    label = acceptance_policy.get("target_label") if isinstance(acceptance_policy, Mapping) else None
    if status == "ready":
        reason = "ready: Aura acceptance satisfied"
    else:
        reason = f"{reason_code}: Aura acceptance {status} at the {stage} gate"
    return {
        "status": status,
        "exit_code": _EXIT_CODES[status],
        "reason_code": reason_code,
        "reason": reason,
        "report": {
            "stage": stage,
            "target_label": label if label in aura_target_store_gate.AURA_LABELS else None,
            "snapshot_sha256": _digest(snapshot),
            "aura_evidence_sha256": _digest(aura_evidence),
        },
    }


def _error_outcome(reason_code: str, detail: str) -> dict[str, Any]:
    return {
        "status": "invalid",
        "exit_code": _EXIT_CODES["invalid"],
        "reason_code": reason_code,
        "reason": f"{reason_code}: {detail}",
        "report": {},
    }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline AuraFace acceptance gate (no live actions).")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--freshness-policy", type=Path, required=True)
    parser.add_argument("--isolation-policy", type=Path, required=True)
    parser.add_argument("--aura-evidence", type=Path, required=True)
    parser.add_argument("--acceptance-policy", type=Path, required=True)
    parser.add_argument("--now", required=True)
    args = parser.parse_args(argv)

    try:
        result = validate_aura_acceptance(
            _load_json(args.snapshot),
            aura_evidence=_load_json(args.aura_evidence),
            freshness_policy=_load_json(args.freshness_policy),
            isolation_policy=_load_json(args.isolation_policy),
            acceptance_policy=_load_json(args.acceptance_policy),
            now=args.now,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        result = _error_outcome("input_unreadable", "unable to read or parse JSON input")
    except Exception as exc:  # fail closed; name only the type so no input content is echoed
        result = _error_outcome("validator_internal_error", f"validator failed unexpectedly ({type(exc).__name__})")
    print(json.dumps(result, sort_keys=True))
    print(result["reason"], file=sys.stderr)
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
