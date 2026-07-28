#!/usr/bin/env python3
"""Permanent discrimination guard for license_policy tests (TEST-15 / BR-11 / BR-17).

Copies license_policy.py + test_license_policy.py into a scratch tree, applies
each known vacuity mutation, runs the suite, and classifies the outcome as
SURVIVED / KILLED / ERROR (never folds import/collection failures into KILLED).

Green baseline is required first. A control mutation must SURVIVE to prove the
harness can report survivors. Defect mutations must be KILLED by at least one
named expected victim test.

Mutations:
  CONTROL  inert comment (must SURVIVE — discrimination proof)
  M1  UNKNOWN_SPDX default-deny flipped to PASS
  M2  delete 'insightface/*' from NC_MODEL_PATTERNS
  M3  NC_MODEL_IDS = frozenset()
  M4  collapse _looks_like_research_source to exact frozenset membership
  M5  REQUIRED_MODEL_INGEST_DISPLAY_NAMES = ()  (suite must still hard-code names)
  M6  _synthetic_audit_targets: empty (source, derived) token loop
  M7  row-category ValueError handler → pass
  M8  research compact match: drop startswith (exact only)
  M9  audit_derived_from_model non-str guard → if False
  M10 disable has_generator_lineage synthetic routing branch

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
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# Resolve all inputs relative to this file — never the process cwd.
_HERE = Path(__file__).resolve().parent
_POLICY = _HERE / "license_policy.py"
_TEST = _HERE / "test_license_policy.py"
_REPO_ROOT = _HERE.parents[2]


class Verdict(str, Enum):
    SURVIVED = "SURVIVED"
    KILLED = "KILLED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class Mutation:
    name: str
    description: str
    apply: str  # key into _APPLIERS
    # Node-id substrings; at least one must appear among FAILED tests on KILLED.
    expected_victims: tuple[str, ...] = ()
    # CONTROL: True — must SURVIVE. Defect mutants: False — must be KILLED.
    expect_survived: bool = False
    # When True, a SURVIVED result fails the guard. False for known open gaps
    # (M6–M10) that stay green until the companion test lane lands; they are
    # still registered and reported so they cannot rot invisibly.
    require_kill: bool = True
    target: str = "policy"  # "policy" | "test"


# ---------------------------------------------------------------------------
# Appliers — each verifies its anchor and raises RuntimeError if missing.
# ---------------------------------------------------------------------------


def _m_control_inert_comment(src: str) -> str:
    """Semantically inert comment above a real function (must SURVIVE)."""
    old = "def _looks_like_research_source(value: str) -> bool:"
    new = (
        "# MUTATION CONTROL: inert comment — harness discrimination probe\n"
        "def _looks_like_research_source(value: str) -> bool:"
    )
    if old not in src:
        raise RuntimeError("CONTROL: could not locate _looks_like_research_source anchor")
    return src.replace(old, new, 1)


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
    if old not in src:
        raise RuntimeError("M1: could not locate UNKNOWN_SPDX fail branch anchor")
    return src.replace(old, new, 1)


def _m2_drop_insightface_star(src: str) -> str:
    """Delete the insightface/* entry from NC_MODEL_PATTERNS."""
    old = 'NC_MODEL_PATTERNS: tuple[str, ...] = (\n    "insightface/*",\n    "insightface",\n'
    new = 'NC_MODEL_PATTERNS: tuple[str, ...] = (\n    "insightface",\n'
    if old not in src:
        raise RuntimeError("M2: could not locate insightface/* in NC_MODEL_PATTERNS")
    return src.replace(old, new, 1)


def _m3_empty_nc_ids(src: str) -> str:
    """Force NC_MODEL_IDS to empty frozenset (disable second matching layer)."""
    pattern = re.compile(
        r"NC_MODEL_IDS:\s*frozenset\[str\]\s*=\s*_derive_nc_model_ids\(\)"
    )
    updated, n = pattern.subn("NC_MODEL_IDS: frozenset[str] = frozenset()", src, count=1)
    if n != 1:
        raise RuntimeError("M3: could not locate NC_MODEL_IDS assignment")
    return updated


def _m4_exact_research_only(src: str) -> str:
    """Collapse _looks_like_research_source to exact frozenset membership."""
    pattern = re.compile(
        r"def _looks_like_research_source\(value: str\) -> bool:.*?(?=\ndef )",
        re.DOTALL,
    )
    replacement = (
        "def _looks_like_research_source(value: str) -> bool:\n"
        '    """MUTATION M4: exact frozenset membership only."""\n'
        "    token = _normalize_token(value)\n"
        "    return token in RESEARCH_ONLY_SOURCES\n\n\n"
    )
    updated, n = pattern.subn(replacement, src, count=1)
    if n != 1:
        raise RuntimeError("M4: could not locate _looks_like_research_source")
    return updated


def _m5_empty_required_names(src: str) -> str:
    """Empty REQUIRED_MODEL_INGEST_DISPLAY_NAMES production tuple."""
    pattern = re.compile(
        r"REQUIRED_MODEL_INGEST_DISPLAY_NAMES:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\("
        r"\s*\*REQUIRED_DETECTOR_AB_DISPLAY_NAMES,\s*"
        r"\*REQUIRED_CASCADE_PERSON_DETECTOR_DISPLAY_NAMES,\s*\)",
        re.DOTALL,
    )
    updated, n = pattern.subn(
        "REQUIRED_MODEL_INGEST_DISPLAY_NAMES: tuple[str, ...] = ()",
        src,
        count=1,
    )
    if n != 1:
        raise RuntimeError(
            "M5: could not locate REQUIRED_MODEL_INGEST_DISPLAY_NAMES anchor"
        )
    return updated


def _m6_empty_synthetic_token_loop(src: str) -> str:
    """Disable SYNTHETIC_SOURCE_ENTRIES routing via (source, derived) loop."""
    old = "    for token in (source, derived):"
    new = "    for token in ():  # MUTATION M6: skip synthetic entry token audit"
    if old not in src:
        raise RuntimeError(
            "M6: could not locate 'for token in (source, derived):' in "
            "_synthetic_audit_targets"
        )
    # Prefer the occurrence inside _synthetic_audit_targets (only one today).
    return src.replace(old, new, 1)


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
    if old not in src:
        raise RuntimeError(
            "M7: could not locate row-category except ValueError → INVALID_ROW block"
        )
    return src.replace(old, new, 1)


def _m8_research_exact_only(src: str) -> str:
    """Drop startswith compound match in research-source compact scan."""
    old = (
        "            if norm.compact.startswith(src) and _research_unsplit_remainder_ok(\n"
        "                norm.compact[len(src) :]\n"
        "            ):"
    )
    new = "            if False:  # MUTATION M8: no unsplit compound startswith match"
    if old not in src:
        raise RuntimeError(
            "M8: could not locate the unsplit-compound startswith branch in "
            "_looks_like_research_source"
        )
    return src.replace(old, new, 1)


def _m9_skip_derived_type_guard(src: str) -> str:
    """Disable non-str guard in audit_derived_from_model."""
    old = "    if not isinstance(derived_from_model, str):"
    new = "    if False:  # MUTATION M9: skip non-str type guard"
    if old not in src:
        raise RuntimeError(
            "M9: could not locate 'if not isinstance(derived_from_model, str):'"
        )
    return src.replace(old, new, 1)


def _m10_disable_generator_lineage_branch(src: str) -> str:
    """Disable has_generator_lineage synthetic routing (FIR-7-BR-16)."""
    old = "    if has_generator_lineage and source:"
    new = "    if False and has_generator_lineage and source:  # MUTATION M10"
    if old not in src:
        raise RuntimeError(
            "M10: could not locate 'if has_generator_lineage and source:'"
        )
    return src.replace(old, new, 1)


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
        description="delete insightface/* from NC_MODEL_PATTERNS",
        apply="m2",
        expected_victims=(
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
    # M6–M10: the four surviving mutants round 2 found, plus BR-16. They
    # survived the 91-test suite; the companion test lane has since landed
    # dedicated tests, so require_kill=True — a regression that re-opens any
    # of these branches must fail the gate rather than be listed as a known
    # survivor. expected_victims are the branch-specific tests measured to
    # fail under each mutant, not collateral kills.
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
        description="research match: drop unsplit-compound startswith branch",
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
]

_APPLIERS = {
    "control": _m_control_inert_comment,
    "m1": _m1_unknown_spdx_pass,
    "m2": _m2_drop_insightface_star,
    "m3": _m3_empty_nc_ids,
    "m4": _m4_exact_research_only,
    "m5": _m5_empty_required_names,
    "m6": _m6_empty_synthetic_token_loop,
    "m7": _m7_category_valueerror_pass,
    "m8": _m8_research_exact_only,
    "m9": _m9_skip_derived_type_guard,
    "m10": _m10_disable_generator_lineage_branch,
}

_FAILED_COUNT_RE = re.compile(r"\b(\d+)\s+failed\b")
_FAILED_NODE_RE = re.compile(r"^FAILED\s+(\S+)", re.MULTILINE)


def _summary_line(out: str) -> str:
    lines = [ln for ln in out.splitlines() if ln.strip()]
    return lines[-1] if lines else "(no output)"


def _failed_nodeids(out: str) -> list[str]:
    return _FAILED_NODE_RE.findall(out)


def _has_failed_tests(out: str) -> bool:
    m = _FAILED_COUNT_RE.search(out)
    return bool(m and int(m.group(1)) >= 1)


def classify_suite_result(rc: int, out: str) -> Verdict:
    """Three-way classification (FIR-7-BR-17 / TEST-15).

    - rc == 0 → SURVIVED
    - rc == 1 and summary reports ≥1 failed → KILLED
    - anything else (rc >= 2, import/collection errors, no tests ran,
      empty output, rc==1 without a failed-test summary) → ERROR
    """
    text = out or ""
    if not text.strip():
        return Verdict.ERROR
    lower = text.lower()
    if "no tests ran" in lower or "no tests collected" in lower:
        return Verdict.ERROR
    # Collection/import failures often surface as "error" without "failed".
    if rc == 0:
        return Verdict.SURVIVED
    if rc == 1 and _has_failed_tests(text):
        return Verdict.KILLED
    return Verdict.ERROR


def _victims_matched(failed_nodes: list[str], expected: tuple[str, ...]) -> list[str]:
    if not expected:
        return []
    hits: list[str] = []
    for exp in expected:
        for node in failed_nodes:
            if exp in node and exp not in hits:
                hits.append(exp)
                break
    return hits


def _run_suite(scratch_dir: Path) -> tuple[int, str]:
    """Run the license_policy suite against a scratch copy. Returns (rc, output)."""
    test_path = scratch_dir / "test_license_policy.py"
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(test_path),
        "-q",
        "--tb=no",
    ]
    env = dict(os.environ)
    proc = subprocess.run(
        cmd,
        cwd=str(scratch_dir),
        capture_output=True,
        text=True,
        env=env,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out


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


def _run_baseline() -> tuple[bool, str]:
    """Unmutated suite must be green before any mutant verdict is meaningful."""
    with tempfile.TemporaryDirectory(prefix="licpol-baseline-") as tmp:
        occ = _prepare_scratch(Path(tmp))
        rc, out = _run_suite(occ)
        summary = _summary_line(out)
        if rc == 0 and classify_suite_result(rc, out) is Verdict.SURVIVED:
            return True, summary
        return False, f"rc={rc} summary={summary!r}\n{out}"


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

    selected = (
        MUTATIONS
        if args.mutation == "all"
        else [m for m in MUTATIONS if m.name == args.mutation]
    )

    # --- Green baseline first (FIR-7-BR-17) ---------------------------------
    print("BASELINE: running unmutated suite...", flush=True)
    ok, baseline_info = _run_baseline()
    if not ok:
        # Write the ERROR on stdout so it cannot be reordered past the
        # BASELINE line when stderr is merged (CI logs, 2>&1).
        print(
            "ERROR: baseline suite is not green; aborting mutation guard.\n"
            "Every downstream verdict is meaningless if the unmutated suite fails.\n"
            f"{baseline_info}",
            flush=True,
        )
        return 2
    print(f"BASELINE: green ({baseline_info})", flush=True)
    print(flush=True)

    survivors: list[str] = []
    killed: list[str] = []
    errors: list[str] = []
    unexpected: list[str] = []  # wrong expect_survived / require_kill mismatch

    original = _POLICY.read_text(encoding="utf-8")

    for mutation in selected:
        with tempfile.TemporaryDirectory(prefix=f"licpol-{mutation.name}-") as tmp:
            base = Path(tmp)
            occ = _prepare_scratch(base)
            try:
                mutated = _apply_mutation(original, mutation)
            except RuntimeError as exc:
                errors.append(mutation.name)
                print(f"ERROR    {mutation.name}: anchor/apply failure: {exc}")
                print(f"  detail: missing anchor must never be reported as SURVIVED")
                continue
            if mutated == original:
                errors.append(mutation.name)
                print(f"ERROR    {mutation.name}: mutation was a no-op (anchor miss)")
                continue
            (occ / "license_policy.py").write_text(mutated, encoding="utf-8")
            rc, out = _run_suite(occ)
            verdict = classify_suite_result(rc, out)
            summary = _summary_line(out)
            failed_nodes = _failed_nodeids(out)

            if verdict is Verdict.ERROR:
                errors.append(mutation.name)
                print(f"ERROR    {mutation.name}: {mutation.description}")
                print(f"  suite: {summary}")
                print(f"  rc={rc} (not a clean test failure — refusing to count as KILLED)")
                # Surface a short diagnostic tail for import/pytest problems.
                tail = "\n".join(out.strip().splitlines()[-5:]) if out.strip() else ""
                if tail:
                    print(f"  diag: {tail}")
                continue

            if verdict is Verdict.SURVIVED:
                survivors.append(mutation.name)
                print(f"SURVIVED {mutation.name}: {mutation.description}")
                print(f"  suite: {summary}")
                if mutation.expect_survived:
                    print("  expect: SURVIVED (control / discrimination OK)")
                elif mutation.require_kill:
                    unexpected.append(mutation.name)
                    print("  expect: KILLED — defect mutant survived (FAIL)")
                else:
                    print(
                        "  expect: tracked open gap (require_kill=False); "
                        "reported honestly, not failing the gate yet"
                    )
                continue

            # verdict is KILLED
            hits = _victims_matched(failed_nodes, mutation.expected_victims)
            if mutation.expect_survived:
                # Control (or any must-survive) came back KILLED → harness broken.
                errors.append(mutation.name)
                print(f"ERROR    {mutation.name}: expected SURVIVED but suite went red")
                print(f"  suite: {summary}")
                print(
                    "  reason: discrimination failure — harness cannot report a "
                    "true survivor (TEST-15)"
                )
                continue
            if mutation.expected_victims and not hits:
                errors.append(mutation.name)
                print(f"ERROR    {mutation.name}: {mutation.description}")
                print(f"  suite: {summary}")
                print(
                    "  reason: suite went red but NONE of the expected victims "
                    f"failed: {mutation.expected_victims}"
                )
                print(f"  failed: {failed_nodes[:12]}")
                print(
                    "  a kill by an unrelated test does not prove the branch "
                    "under test is guarded"
                )
                continue

            killed.append(mutation.name)
            print(f"KILLED   {mutation.name}: {mutation.description}")
            print(f"  suite: {summary}")
            if hits:
                print(f"  victims: {', '.join(hits)}")

    print()
    print(
        f"killed={len(killed)} survivors={len(survivors)} "
        f"errors={len(errors)} total={len(selected)}"
    )
    if survivors:
        print("survivors: " + ", ".join(survivors))
    if errors:
        print("errors: " + ", ".join(errors))

    # Exit policy:
    # 1. Any ERROR → non-zero (never certify on broken harness / missing anchor).
    # 2. CONTROL (expect_survived) not SURVIVED → already in errors.
    # 3. require_kill mutants that SURVIVED → non-zero.
    # 4. Tracked open gaps (require_kill=False) may SURVIVE without failing the gate.
    if errors:
        print("FAIL: guard errors (import/collection/anchor/victim/discrimination)")
        return 2
    if unexpected:
        print("FAIL: required-kill mutants survived: " + ", ".join(unexpected))
        return 1

    # Confirm control was in the run when --mutation all
    control_selected = any(m.name == "CONTROL" for m in selected)
    if control_selected and "CONTROL" not in survivors:
        # Should have been caught as ERROR above; belt-and-braces.
        print("FAIL: CONTROL did not SURVIVE — harness not discriminating (TEST-15)")
        return 1

    if survivors and any(
        m.name in survivors and not m.expect_survived and not m.require_kill
        for m in selected
    ):
        open_gaps = [
            m.name
            for m in selected
            if m.name in survivors and not m.expect_survived and not m.require_kill
        ]
        print(
            "OK: required mutants killed; control survived; "
            f"open-gap survivors (not gated yet): {', '.join(open_gaps)}"
        )
        return 0

    print("OK: all required mutants killed; control survived")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
