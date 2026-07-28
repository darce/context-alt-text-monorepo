#!/usr/bin/env python3
"""Permanent discrimination guard for license_policy tests (TEST-15 / BR-11 / BR-17).

Copies license_policy.py + test_license_policy.py into a scratch tree, applies
each known vacuity mutation, runs the suite, and classifies the outcome as
SURVIVED / KILLED / HARNESS-ERROR (never folds import/collection failures into
KILLED).

Green baseline is required first. A control mutation must SURVIVE to prove the
harness can report survivors. Defect mutations must be KILLED by at least one
named expected victim test.

Harness integrity (BR-49 / SECD-03 / SECD-05 / TEST-15):
  * Subprocess env is built from an explicit allowlist (not os.environ copy).
  * Results come from junitxml on disk, not stdout text parsing.
  * Every mutant run must execute the same number of testcases as baseline.

Mutations:
  CONTROL  inert comment (must SURVIVE — discrimination proof)
  M1  UNKNOWN_SPDX default-deny flipped to PASS
  M2  drop insightface family from NC_MODEL_IDS (verdict-flipping; B4b)
  M3  NC_MODEL_IDS = frozenset()
  M4  collapse _looks_like_research_source to exact frozenset membership
  M5  REQUIRED_MODEL_INGEST_DISPLAY_NAMES = ()  (suite must still hard-code names)
  M6  _synthetic_audit_targets: empty (source, derived) token loop
  M7  row-category ValueError handler → pass
  M8  research expand: drop unsplit compound forms (single site after B4b / BR-47)
  M9  audit_derived_from_model non-str guard → if False
  M10 disable has_generator_lineage synthetic routing branch
  M11 slash-component membership disabled (dataset/ffhq path hits)
  M12 get_model_ingest_entry primary raise → pass (xfail_until_b4c; known gap)

Paths resolve from __file__ (never cwd) so this script runs as documented from
the repo root or from this directory (rg-006).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# Resolve all inputs relative to this file — never the process cwd.
_HERE = Path(__file__).resolve().parent
_POLICY = _HERE / "license_policy.py"
_TEST = _HERE / "test_license_policy.py"
_REPO_ROOT = _HERE.parents[2]

# Explicit env allowlist for child pytest (BR-49). Blocklist would rot.
_ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LC_MESSAGES",
        "LC_NUMERIC",
        "LC_TIME",
        "LC_COLLATE",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "COMSPEC",
        "WINDIR",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
    }
)

# Must never reach the child, even if somehow present on the allowlist later.
_ENV_DENY_EXACT = frozenset(
    {
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONHOME",
        "PYTHONWARNINGS",
        "PYTEST_CURRENT_TEST",
    }
)


class Verdict(str, Enum):
    SURVIVED = "SURVIVED"
    KILLED = "KILLED"
    HARNESS_ERROR = "HARNESS-ERROR"


@dataclass(frozen=True)
class Mutation:
    name: str
    description: str
    apply: str  # key into _APPLIERS
    # Exact test-name components (or base name before [param]); at least one
    # must appear among FAILED tests on KILLED.
    expected_victims: tuple[str, ...] = ()
    # CONTROL: True — must SURVIVE. Defect mutants: False — must be KILLED.
    expect_survived: bool = False
    # When True, a SURVIVED result fails the guard. False for known open gaps
    # that stay green until a companion lane lands; they are still registered
    # and reported so they cannot rot invisibly.
    require_kill: bool = True
    target: str = "policy"  # "policy" | "test"
    # When True, SURVIVED is reported as a known gap (B4c owns the victim).
    xfail_until_b4c: bool = False


@dataclass(frozen=True)
class SuiteReport:
    """Machine-readable suite outcome from junitxml + process rc."""

    rc: int
    executed: int
    failed_names: tuple[str, ...]  # test-name components that failed/errored
    summary: str
    raw_out: str
    junit_path: Path | None
    parse_error: str | None = None


# ---------------------------------------------------------------------------
# Anchor helpers (BR-17)
# ---------------------------------------------------------------------------


class AnchorError(RuntimeError):
    """Raised when a mutation anchor is missing or not unique."""


def _assert_unique_anchor(src: str, anchor: str, mut_name: str) -> None:
    """Require ``anchor`` to occur exactly once in pristine source (BR-17)."""
    n = src.count(anchor)
    if n != 1:
        raise AnchorError(
            f"ANCHOR-ERROR {mut_name}: anchor occurs {n} time(s), expected exactly 1"
        )


def _replace_unique(src: str, old: str, new: str, mut_name: str) -> str:
    _assert_unique_anchor(src, old, mut_name)
    return src.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Appliers — each verifies its anchor and raises if missing / non-unique.
# ---------------------------------------------------------------------------


def _m_control_inert_comment(src: str) -> str:
    """Semantically inert comment above a real function (must SURVIVE)."""
    old = "def _looks_like_research_source(value: str) -> bool:"
    new = (
        "# MUTATION CONTROL: inert comment — harness discrimination probe\n"
        "def _looks_like_research_source(value: str) -> bool:"
    )
    return _replace_unique(src, old, new, "CONTROL")


def _m1_unknown_spdx_pass(src: str) -> str:
    """Flip UNKNOWN_SPDX default-deny to PASS."""
    old = (
        "    # operator-cleared is NOT an SPDX value and is never an unconditional pass.\n"
        "    return _fail(\n"
        "        RejectionReason.UNKNOWN_SPDX,\n"
        "        detail=f\"license {tag!r} is not on the allowlist\",\n"
        "    )"
    )
    new = (
        "    # MUTATION M1: unknown SPDX incorrectly PASSes\n"
        "    return _pass(detail=f\"license {tag!r} unknown but mutated to pass\")"
    )
    return _replace_unique(src, old, new, "M1")


def _m2_drop_insightface_patterns(src: str) -> str:
    """Drop insightface family from NC seed set (verdict-flipping; B4b re-point).

    After B4b, matching is exact expanded-id membership. Removing every
    insightface-bearing seed from ``NC_MODEL_IDS`` flips
    ``insightface_buffalo_l`` / nested ``…/insightface/…`` from FAIL→PASS
    while buffalo_* pack ids remain denied.
    """
    old = "NC_MODEL_IDS: frozenset[str] = _derive_nc_model_ids()"
    new = (
        "NC_MODEL_IDS: frozenset[str] = frozenset(  # MUTATION M2: drop insightface family\n"
        '    x for x in _derive_nc_model_ids() if "insightface" not in x\n'
        ")"
    )
    return _replace_unique(src, old, new, "M2")



def _m3_empty_nc_ids(src: str) -> str:
    """Force NC_MODEL_IDS to empty frozenset (disable second matching layer)."""
    pattern = re.compile(
        r"NC_MODEL_IDS:\s*frozenset\[str\]\s*=\s*_derive_nc_model_ids\(\)"
    )
    matches = pattern.findall(src)
    if len(matches) != 1:
        raise AnchorError(
            f"ANCHOR-ERROR M3: NC_MODEL_IDS assignment occurs {len(matches)} time(s), "
            "expected exactly 1"
        )
    updated, n = pattern.subn(
        "NC_MODEL_IDS: frozenset[str] = frozenset()", src, count=1
    )
    if n != 1:
        raise AnchorError("ANCHOR-ERROR M3: could not locate NC_MODEL_IDS assignment")
    return updated


def _m4_exact_research_only(src: str) -> str:
    """Collapse _looks_like_research_source to exact frozenset membership."""
    pattern = re.compile(
        r"def _looks_like_research_source\(value: str\) -> bool:.*?(?=\ndef )",
        re.DOTALL,
    )
    found = pattern.findall(src)
    if len(found) != 1:
        raise AnchorError(
            f"ANCHOR-ERROR M4: _looks_like_research_source occurs {len(found)} time(s), "
            "expected exactly 1"
        )
    replacement = (
        "def _looks_like_research_source(value: str) -> bool:\n"
        '    """MUTATION M4: exact frozenset membership only."""\n'
        "    token = _normalize_token(value)\n"
        "    return token in RESEARCH_ONLY_SOURCES\n\n\n"
    )
    updated, n = pattern.subn(replacement, src, count=1)
    if n != 1:
        raise AnchorError("ANCHOR-ERROR M4: could not locate _looks_like_research_source")
    return updated


def _m5_empty_required_names(src: str) -> str:
    """Empty REQUIRED_MODEL_INGEST_DISPLAY_NAMES production tuple."""
    pattern = re.compile(
        r"REQUIRED_MODEL_INGEST_DISPLAY_NAMES:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\("
        r"\s*\*REQUIRED_DETECTOR_AB_DISPLAY_NAMES,\s*"
        r"\*REQUIRED_CASCADE_PERSON_DETECTOR_DISPLAY_NAMES,\s*\)",
        re.DOTALL,
    )
    found = pattern.findall(src)
    if len(found) != 1:
        raise AnchorError(
            f"ANCHOR-ERROR M5: REQUIRED_MODEL_INGEST_DISPLAY_NAMES occurs "
            f"{len(found)} time(s), expected exactly 1"
        )
    updated, n = pattern.subn(
        "REQUIRED_MODEL_INGEST_DISPLAY_NAMES: tuple[str, ...] = ()",
        src,
        count=1,
    )
    if n != 1:
        raise AnchorError(
            "ANCHOR-ERROR M5: could not locate REQUIRED_MODEL_INGEST_DISPLAY_NAMES"
        )
    return updated


def _m6_empty_synthetic_token_loop(src: str) -> str:
    """Disable SYNTHETIC_SOURCE_ENTRIES routing via (source, derived) loop."""
    old = "    for token in (source, derived):"
    new = "    for token in ():  # MUTATION M6: skip synthetic entry token audit"
    return _replace_unique(src, old, new, "M6")


def _m7_category_valueerror_pass(src: str) -> str:
    """Row-category parse ValueError handler returns nothing (pass)."""
    old = (
        "    except ValueError:\n"
        "        return None, _fail(\n"
        "            RejectionReason.INVALID_ROW,\n"
        "            detail=f\"unknown policy category {raw_cat!r}\",\n"
        "            category=audit_category,\n"
        "        )"
    )
    new = (
        "    except ValueError:\n"
        "        return None, None  # MUTATION M7: invalid category silently ignored"
    )
    return _replace_unique(src, old, new, "M7")


def _m8_research_exact_only(src: str) -> str:
    """Drop unsplit compound forms from registry-side expansion (B4b / BR-47).

    Single surviving implementation: import-time ``_expand_id_forms`` adds
    unsplit ``base+suffix`` forms (ffhq256, widerfacehd). Disabling that line
    flips ``test_br27_unsplit_compounds_still_fail``.
    """
    old = '        unsplit = f"{_compact_canonical(c)}{suf}"  # unsplit compound startswith-equivalent'
    new = '        unsplit = ""  # MUTATION M8: no unsplit compound expansion'
    return _replace_unique(src, old, new, "M8")



def _m9_skip_derived_type_guard(src: str) -> str:
    """Disable non-str guard in audit_derived_from_model."""
    old = "    if not isinstance(derived_from_model, str):"
    new = "    if False:  # MUTATION M9: skip non-str type guard"
    return _replace_unique(src, old, new, "M9")


def _m10_disable_generator_lineage_branch(src: str) -> str:
    """Disable has_generator_lineage synthetic routing (FIR-7-BR-16)."""
    old = "    if has_generator_lineage and source:"
    new = "    if False and has_generator_lineage and source:  # MUTATION M10"
    return _replace_unique(src, old, new, "M10")


def _m11_collapse_separator_parity(src: str) -> str:
    """Disable slash-component exact membership (B4b re-point of M11).

    Under exact enumeration, separator parity lives in :func:`canonical`.
    Slash-component hits such as ``dataset/ffhq`` are the remaining
    path-shape branch; dropping them flips research slash-form controls.
    """
    old = (
        "    # Slash components only — never progressive underscore prefixes (BR-50/52).\n"
        '    if "/" in c:\n'
        '        for part in c.split("/"):'
    )
    new = (
        "    # MUTATION M11: slash-component membership disabled\n"
        '    if False and "/" in c:\n'
        '        for part in c.split("/"):'
    )
    return _replace_unique(src, old, new, "M11")



def _m12_ingest_entry_raise_pass(src: str) -> str:
    """Primary raise LicensePolicyError(result) in get_model_ingest_entry → pass.

    BR-62/B4c: the full suite currently stays green under this mutation.
    Registered with expected_victims=[] and xfail_until_b4c so the guard
    reports a KNOWN GAP rather than a silent kill.
    """
    old = (
        "    result = audit_model_ingest(model_id)\n"
        "    if not result.ok:\n"
        "        raise LicensePolicyError(result)"
    )
    new = (
        "    result = audit_model_ingest(model_id)\n"
        "    if not result.ok:\n"
        "        pass  # MUTATION M12: swallow primary LicensePolicyError"
    )
    return _replace_unique(src, old, new, "M12")


MUTATIONS: list[Mutation] = [
    Mutation(
        name="CONTROL",
        description="inert comment above _looks_like_research_source (discrimination)",
        apply="control",
        expected_victims=(),
        expect_survived=True,
        require_kill=False,
    ),
    Mutation(
        name="M1",
        description="UNKNOWN_SPDX default-deny → PASS",
        apply="m1",
        expected_victims=(
            "test_unknown_spdx_default_deny",
            "test_operator_cleared_is_not_spdx_pass",
            "test_operator_cleared_row_fails",
        ),
    ),
    Mutation(
        name="M2",
        description="drop insightface family from NC_MODEL_IDS (verdict-flip; B4b)",
        apply="m2",
        expected_victims=(
            "test_nested_and_separator_insightface_forms_fail",
            "test_insightface_prefix_pattern_is_pinned",
        ),
    ),
    Mutation(
        name="M3",
        description="NC_MODEL_IDS = frozenset()",
        apply="m3",
        expected_victims=(
            "test_nc_model_ids_layer_rejects_pinned_ids",
            "test_vec2face_forbidden_table_entry_drives_nc_ids",
        ),
    ),
    Mutation(
        name="M4",
        description="_looks_like_research_source → exact frozenset membership",
        apply="m4",
        expected_victims=(
            "test_research_source_fails_with_research_only_reason",
        ),
    ),
    Mutation(
        name="M5",
        description="REQUIRED_MODEL_INGEST_DISPLAY_NAMES = ()",
        apply="m5",
        expected_victims=(
            "test_required_display_names_registered",
        ),
    ),
    Mutation(
        name="M6",
        description="_synthetic_audit_targets: for token in () (skip entry loop)",
        apply="m6",
        expected_victims=(
            "test_br29_dcface_no_lineage_wrong_clearance_fails",
            "test_br29_dcface_no_lineage_missing_clearance_fails",
            "test_br36_dcface_v2_no_lineage_still_requires_clearance",
        ),
    ),
    Mutation(
        name="M7",
        description="row-category except ValueError → pass (invalid category ignored)",
        apply="m7",
        expected_victims=("test_row_cannot_waive_source_via_bogus_category",),
    ),
    Mutation(
        name="M8",
        description="research expand: drop unsplit-compound forms (B4b single site)",
        apply="m8",
        expected_victims=("test_br27_unsplit_compounds_still_fail",),
    ),
    Mutation(
        name="M9",
        description="audit_derived_from_model type guard → if False",
        apply="m9",
        expected_victims=("test_br37_audit_derived_from_model_rejects_non_string",),
    ),
    Mutation(
        name="M10",
        description="disable has_generator_lineage synthetic routing (BR-16)",
        apply="m10",
        expected_victims=("test_br16_lineage_sole_cause_of_synthetic_pending",),
    ),
    Mutation(
        name="M11",
        description="slash-component membership disabled (B4b separator-parity site)",
        apply="m11",
        expected_victims=(
            "test_research_source_fails_with_research_only_reason",
            "test_br27_controls_still_fail_research",
        ),
    ),
    Mutation(
        name="M12",
        description="get_model_ingest_entry primary raise → pass (known gap until B4c)",
        apply="m12",
        expected_victims=(),
        require_kill=False,
        xfail_until_b4c=True,
    ),
]

_APPLIERS = {
    "control": _m_control_inert_comment,
    "m1": _m1_unknown_spdx_pass,
    "m2": _m2_drop_insightface_patterns,
    "m3": _m3_empty_nc_ids,
    "m4": _m4_exact_research_only,
    "m5": _m5_empty_required_names,
    "m6": _m6_empty_synthetic_token_loop,
    "m7": _m7_category_valueerror_pass,
    "m8": _m8_research_exact_only,
    "m9": _m9_skip_derived_type_guard,
    "m10": _m10_disable_generator_lineage_branch,
    "m11": _m11_collapse_separator_parity,
    "m12": _m12_ingest_entry_raise_pass,
}


# ---------------------------------------------------------------------------
# Subprocess env + junitxml (BR-49)
# ---------------------------------------------------------------------------


def _scrubbed_env() -> dict[str, str]:
    """Build child env from an allowlist; pytest/python injection vars excluded."""
    env: dict[str, str] = {}
    for key, val in os.environ.items():
        if key in _ENV_DENY_EXACT:
            continue
        if key.startswith("PYTEST_DEBUG"):
            continue
        if key.startswith("PYTEST_"):
            continue
        if key in _ENV_ALLOWLIST or key.startswith("LC_"):
            env[key] = val
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    # Belt: ensure injection vectors are absent even if allowlist grows.
    for bad in _ENV_DENY_EXACT:
        env.pop(bad, None)
    for key in list(env):
        if key.startswith("PYTEST_DEBUG") or (
            key.startswith("PYTEST_") and key != "PYTEST_DISABLE_PLUGIN_AUTOLOAD"
        ):
            env.pop(key, None)
    return env


def _parse_junitxml(junit_path: Path) -> tuple[int, list[str], str | None]:
    """Return (executed_count, failed_test_names, parse_error).

    Failed names are the pytest test-name component (``name`` attribute),
    including parametrised ``name[param]`` form when present.
    """
    if not junit_path.is_file():
        return 0, [], f"junitxml missing: {junit_path}"
    try:
        tree = ET.parse(junit_path)
    except ET.ParseError as exc:
        return 0, [], f"junitxml parse error: {exc}"
    root = tree.getroot()
    # pytest may emit <testsuites><testsuite>… or a bare <testsuite>.
    cases = root.findall(".//testcase")
    failed: list[str] = []
    for case in cases:
        name = case.get("name") or ""
        # failure / error children mark a non-pass (skip is neither).
        if case.find("failure") is not None or case.find("error") is not None:
            failed.append(name)
    return len(cases), failed, None


def classify_suite_result(
    report: SuiteReport,
    *,
    baseline_executed: int | None = None,
) -> Verdict:
    """Three-way classification (FIR-7-BR-17 / BR-49 / TEST-15).

    - rc == 0 → SURVIVED
    - executed count ≠ baseline → HARNESS-ERROR (forgery / collection miss)
    - rc == 1 and ≥1 failed testcase in junit → KILLED
    - anything else (rc >= 2, import/collection errors, missing junit,
      rc==1 without failed testcases) → HARNESS-ERROR
    """
    if report.parse_error:
        return Verdict.HARNESS_ERROR
    if report.executed < 1:
        return Verdict.HARNESS_ERROR
    if baseline_executed is not None and report.executed != baseline_executed:
        return Verdict.HARNESS_ERROR
    if report.rc == 0:
        return Verdict.SURVIVED
    if report.rc == 1 and report.failed_names:
        return Verdict.KILLED
    return Verdict.HARNESS_ERROR


def _test_name_from_nodeid(node: str) -> str:
    """Last ``::`` component of a nodeid (``name`` or ``name[param]``)."""
    return node.rsplit("::", 1)[-1]


def _victims_matched(failed_names: list[str], expected: tuple[str, ...]) -> list[str]:
    """Exact test-name match (BR-17) — no substring/prefix matching.

    Parametrised failures use the ``name[param]`` form from junit. An expected
    victim may be either the full ``name[param]`` or the bare function name
    (matches any param of that test). A victim that is only a prefix of another
    test name does **not** match.
    """
    if not expected:
        return []
    hits: list[str] = []
    for exp in expected:
        for raw in failed_names:
            tname = _test_name_from_nodeid(raw)
            base = tname.split("[", 1)[0]
            if exp == tname or exp == base:
                if exp not in hits:
                    hits.append(exp)
                break
    return hits


def _run_suite(scratch_dir: Path) -> SuiteReport:
    """Run the license_policy suite against a scratch copy; parse junitxml."""
    test_path = scratch_dir / "test_license_policy.py"
    junit_path = scratch_dir / "report.xml"
    if junit_path.exists():
        junit_path.unlink()
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(test_path),
        "-q",
        "--tb=no",
        "-p",
        "no:cacheprovider",
        f"--junitxml={junit_path}",
    ]
    env = _scrubbed_env()
    proc = subprocess.run(
        cmd,
        cwd=str(scratch_dir),
        capture_output=True,
        text=True,
        env=env,
    )
    raw = (proc.stdout or "") + (proc.stderr or "")
    executed, failed_names, parse_error = _parse_junitxml(junit_path)
    # Build summary from the same fields the dataclass will hold.
    if parse_error:
        summary = f"HARNESS-ERROR ({parse_error})"
    else:
        n_fail = len(failed_names)
        n_ok = executed - n_fail
        if proc.returncode == 0:
            summary = f"{executed} passed (junit executed={executed})"
        else:
            summary = (
                f"{n_fail} failed, {n_ok} passed "
                f"(junit executed={executed}, rc={proc.returncode})"
            )
    return SuiteReport(
        rc=proc.returncode,
        executed=executed,
        failed_names=tuple(failed_names),
        summary=summary,
        raw_out=raw,
        junit_path=junit_path if junit_path.is_file() else None,
        parse_error=parse_error,
    )


def _prepare_scratch(base: Path) -> Path:
    """Layout a mini tree the test loader can resolve (parents[3] = repo root)."""
    # test uses Path(__file__).resolve().parents[3] as repo root.
    # __file__ = <scratch>/scripts/train/occlusion/test_license_policy.py
    # parents[0]=occlusion, [1]=train, [2]=scripts, [3]=scratch root
    occ = base / "scripts" / "train" / "occlusion"
    occ.mkdir(parents=True, exist_ok=True)
    (base / "scripts" / "train" / "__init__.py").write_text("", encoding="utf-8")
    (occ / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy2(_POLICY, occ / "license_policy.py")
    shutil.copy2(_TEST, occ / "test_license_policy.py")
    return occ


def _apply_mutation(policy_src: str, mutation: Mutation) -> str:
    applier = _APPLIERS[mutation.apply]
    return applier(policy_src)


def _run_baseline() -> tuple[bool, str, int]:
    """Unmutated suite must be green before any mutant verdict is meaningful.

    Returns (ok, info, baseline_executed).
    """
    with tempfile.TemporaryDirectory(prefix="licpol-baseline-") as tmp:
        occ = _prepare_scratch(Path(tmp))
        report = _run_suite(occ)
        if (
            report.rc == 0
            and report.parse_error is None
            and report.executed >= 1
            and classify_suite_result(report) is Verdict.SURVIVED
        ):
            return True, report.summary, report.executed
        return (
            False,
            f"rc={report.rc} executed={report.executed} "
            f"summary={report.summary!r}\n{report.raw_out}",
            report.executed,
        )


def _parent_env_injection_vars() -> list[str]:
    """Return ambient injection vars that must not be present when the guard runs.

    Child scrub is necessary but not sufficient if an operator (or CI wrapper)
    believes exporting PYTEST_ADDOPTS is harmless. Refuse to certify under a
    tainted parent env (SECD-03 complete mediation).
    """
    bad: list[str] = []
    for key in (
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "PYTHONSTARTUP",
        "PYTHONHOME",
    ):
        if os.environ.get(key):
            bad.append(key)
    # PYTHONPATH is the load path for `-p certify_nothing`-style plugins.
    if os.environ.get("PYTHONPATH"):
        bad.append("PYTHONPATH")
    for key in os.environ:
        if key.startswith("PYTEST_DEBUG") and os.environ.get(key):
            bad.append(key)
    return bad


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mutation",
        choices=[m.name for m in MUTATIONS] + ["all"],
        default="all",
        help="Run a single mutation or all (default: all)",
    )
    args = parser.parse_args(argv)

    if not _POLICY.is_file() or not _TEST.is_file():
        print(
            "ERROR: license_policy.py / test_license_policy.py missing "
            f"(looked under {_HERE})",
            file=sys.stderr,
        )
        return 2

    injected = _parent_env_injection_vars()
    if injected:
        print(
            "HARNESS-ERROR: refusing to run mutation guard under injected "
            f"pytest/python env: {', '.join(injected)}\n"
            "Unset these variables before certifying (BR-49 / SECD-03). "
            "Child subprocesses also scrub via an allowlist; parent refusal "
            "closes the 'export and forget' path.",
            flush=True,
        )
        return 2

    selected = (
        MUTATIONS
        if args.mutation == "all"
        else [m for m in MUTATIONS if m.name == args.mutation]
    )

    # --- Green baseline first (FIR-7-BR-17) ---------------------------------
    print("BASELINE: running unmutated suite...", flush=True)
    ok, baseline_info, baseline_executed = _run_baseline()
    if not ok:
        print(
            "ERROR: baseline suite is not green; aborting mutation guard.\n"
            "Every downstream verdict is meaningless if the unmutated suite fails.\n"
            f"{baseline_info}",
            flush=True,
        )
        return 2
    print(
        f"BASELINE: green ({baseline_info}; baseline_executed={baseline_executed})",
        flush=True,
    )
    print(flush=True)

    survivors: list[str] = []
    killed: list[str] = []
    errors: list[str] = []
    unexpected: list[str] = []  # wrong expect_survived / require_kill mismatch
    known_gaps: list[str] = []

    # Pristine bytes — never leave the tree dirty (restore via scratch only;
    # original path is never written).
    original = _POLICY.read_text(encoding="utf-8")
    original_bytes = _POLICY.read_bytes()

    try:
        for mutation in selected:
            with tempfile.TemporaryDirectory(prefix=f"licpol-{mutation.name}-") as tmp:
                base = Path(tmp)
                occ = _prepare_scratch(base)
                policy_path = occ / "license_policy.py"
                try:
                    mutated = _apply_mutation(original, mutation)
                except AnchorError as exc:
                    errors.append(mutation.name)
                    print(f"HARNESS-ERROR {mutation.name}: {exc}")
                    print(
                        "  detail: non-unique or missing anchor must never be "
                        "reported as SURVIVED/KILLED"
                    )
                    continue
                except RuntimeError as exc:
                    errors.append(mutation.name)
                    print(f"HARNESS-ERROR {mutation.name}: anchor/apply failure: {exc}")
                    print(
                        "  detail: missing anchor must never be reported as SURVIVED"
                    )
                    continue
                if mutated == original:
                    errors.append(mutation.name)
                    print(
                        f"HARNESS-ERROR {mutation.name}: mutation was a no-op "
                        "(anchor miss)"
                    )
                    continue
                policy_path.write_text(mutated, encoding="utf-8")
                report = _run_suite(occ)
                verdict = classify_suite_result(
                    report, baseline_executed=baseline_executed
                )
                summary = report.summary
                failed_names = list(report.failed_names)

                # Explicit discrimination invariant message for count mismatch.
                if (
                    report.parse_error is None
                    and report.executed != baseline_executed
                    and report.executed >= 0
                ):
                    errors.append(mutation.name)
                    print(f"HARNESS-ERROR {mutation.name}: {mutation.description}")
                    print(f"  suite: {summary}")
                    print(
                        f"  reason: executed count {report.executed} != "
                        f"baseline_executed {baseline_executed} "
                        "(forgery / collection error / body no-op plugin)"
                    )
                    continue

                if verdict is Verdict.HARNESS_ERROR:
                    errors.append(mutation.name)
                    print(f"HARNESS-ERROR {mutation.name}: {mutation.description}")
                    print(f"  suite: {summary}")
                    print(
                        f"  rc={report.rc} executed={report.executed} "
                        "(not a clean test failure — refusing to count as KILLED)"
                    )
                    if report.parse_error:
                        print(f"  parse: {report.parse_error}")
                    tail = (
                        "\n".join(report.raw_out.strip().splitlines()[-5:])
                        if report.raw_out.strip()
                        else ""
                    )
                    if tail:
                        print(f"  diag: {tail}")
                    continue

                if verdict is Verdict.SURVIVED:
                    survivors.append(mutation.name)
                    print(f"SURVIVED {mutation.name}: {mutation.description}")
                    print(f"  suite: {summary}")
                    if mutation.expect_survived:
                        print("  expect: SURVIVED (control / discrimination OK)")
                    elif mutation.xfail_until_b4c:
                        known_gaps.append(mutation.name)
                        print(
                            "  expect: KNOWN GAP (xfail_until_b4c) — victim test "
                            "owned by B4c; not counted as a kill"
                        )
                    elif mutation.require_kill:
                        unexpected.append(mutation.name)
                        print("  expect: KILLED — defect mutant survived (FAIL)")
                    else:
                        known_gaps.append(mutation.name)
                        print(
                            "  expect: tracked open gap (require_kill=False); "
                            "reported honestly, not failing the gate yet"
                        )
                    continue

                # verdict is KILLED
                hits = _victims_matched(failed_names, mutation.expected_victims)
                if mutation.expect_survived:
                    errors.append(mutation.name)
                    print(
                        f"HARNESS-ERROR {mutation.name}: expected SURVIVED but "
                        "suite went red"
                    )
                    print(f"  suite: {summary}")
                    print(
                        "  reason: discrimination failure — harness cannot report a "
                        "true survivor (TEST-15)"
                    )
                    continue
                # Mutants with no named victims cannot certify a kill (BR-43 M12).
                if not mutation.expected_victims:
                    if mutation.xfail_until_b4c:
                        known_gaps.append(mutation.name)
                        print(
                            f"KNOWN-GAP {mutation.name}: suite red but "
                            "expected_victims=[] (xfail_until_b4c); not a certified kill"
                        )
                        print(f"  suite: {summary}")
                    else:
                        errors.append(mutation.name)
                        print(
                            f"HARNESS-ERROR {mutation.name}: suite red but no named "
                            "victims registered — refusing to count as KILLED"
                        )
                        print(f"  suite: {summary}")
                        print(f"  failed: {failed_names[:12]}")
                    continue
                if not hits:
                    errors.append(mutation.name)
                    print(f"HARNESS-ERROR {mutation.name}: {mutation.description}")
                    print(f"  suite: {summary}")
                    print(
                        "  reason: suite went red but NONE of the expected victims "
                        f"failed: {mutation.expected_victims}"
                    )
                    print(f"  failed: {failed_names[:12]}")
                    print(
                        "  a kill by an unrelated test does not prove the branch "
                        "under test is guarded"
                    )
                    continue

                killed.append(mutation.name)
                print(f"KILLED   {mutation.name}: {mutation.description}")
                print(f"  suite: {summary}")
                print(f"  victims: {', '.join(hits)}")
    finally:
        # Byte-identical restore guarantee for the real tree (scratch-only writes).
        if _POLICY.read_bytes() != original_bytes:
            _POLICY.write_bytes(original_bytes)

    print()
    print(
        f"killed={len(killed)} survivors={len(survivors)} "
        f"errors={len(errors)} total={len(selected)}"
    )
    if survivors:
        print("survivors: " + ", ".join(survivors))
    if errors:
        print("errors: " + ", ".join(errors))
    if known_gaps:
        print("known_gaps: " + ", ".join(known_gaps))

    # Exit policy:
    # 1. Any HARNESS-ERROR → non-zero (never certify on broken harness / anchor).
    # 2. CONTROL (expect_survived) not SURVIVED → already in errors.
    # 3. require_kill mutants that SURVIVED → non-zero.
    # 4. Tracked open gaps (require_kill=False / xfail_until_b4c) may SURVIVE.
    if errors:
        print(
            "FAIL: guard errors (import/collection/anchor/victim/discrimination/"
            "executed-count)"
        )
        return 2
    if unexpected:
        print("FAIL: required-kill mutants survived: " + ", ".join(unexpected))
        return 1

    control_selected = any(m.name == "CONTROL" for m in selected)
    if control_selected and "CONTROL" not in survivors:
        print("FAIL: CONTROL did not SURVIVE — harness not discriminating (TEST-15)")
        return 1

    if known_gaps or (
        survivors
        and any(
            m.name in survivors and not m.expect_survived and not m.require_kill
            for m in selected
        )
    ):
        open_gaps = sorted(
            set(known_gaps)
            | {
                m.name
                for m in selected
                if m.name in survivors
                and not m.expect_survived
                and not m.require_kill
            }
        )
        print(
            "OK: required mutants killed; control survived; "
            f"open-gap survivors (not gated yet): {', '.join(open_gaps)}"
        )
        return 0

    print("OK: all required mutants killed; control survived")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
