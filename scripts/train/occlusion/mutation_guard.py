#!/usr/bin/env python3
"""Permanent discrimination guard for license_policy tests (TEST-15 / BR-11).

Copies license_policy.py + test_license_policy.py into a scratch tree, applies
each known vacuity mutation, runs the suite, and exits non-zero if ANY mutant
survives (suite stays fully green).

Mutations (must each go RED):
  M1  UNKNOWN_SPDX default-deny flipped to PASS
  M2  delete 'insightface/*' from NC_MODEL_PATTERNS
  M3  NC_MODEL_IDS = frozenset()
  M4  collapse _looks_like_research_source to exact frozenset membership
  M5  REQUIRED_MODEL_INGEST_DISPLAY_NAMES = ()  (suite must still hard-code names)

Also includes control mutations that prove the harness can discriminate.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_POLICY = _HERE / "license_policy.py"
_TEST = _HERE / "test_license_policy.py"
_REPO_ROOT = _HERE.parents[2]


@dataclass(frozen=True)
class Mutation:
    name: str
    description: str
    apply: str  # applied to license_policy.py source unless target=test
    target: str = "policy"  # "policy" | "test"


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
        # Fallback: replace any UNKNOWN_SPDX fail return at end of audit_spdx.
        pattern = re.compile(
            r"return _fail\(\s*RejectionReason\.UNKNOWN_SPDX,.*?\)",
            re.DOTALL,
        )
        updated, n = pattern.subn(
            'return _pass(detail="MUTATION M1 unknown spdx pass")',
            src,
            count=1,
        )
        if n != 1:
            raise RuntimeError("M1: could not locate UNKNOWN_SPDX fail branch")
        return updated
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
    # Replace the assignment after _derive_nc_model_ids().
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
        # Simpler fallback.
        if "REQUIRED_MODEL_INGEST_DISPLAY_NAMES: tuple[str, ...] = (" not in src:
            raise RuntimeError("M5: could not locate REQUIRED_MODEL_INGEST_DISPLAY_NAMES")
        updated = re.sub(
            r"REQUIRED_MODEL_INGEST_DISPLAY_NAMES: tuple\[str, \.\.\.\] = \([^)]*\)",
            "REQUIRED_MODEL_INGEST_DISPLAY_NAMES: tuple[str, ...] = ()",
            src,
            count=1,
            flags=re.DOTALL,
        )
        if updated == src:
            raise RuntimeError("M5: replacement failed")
    return updated


MUTATIONS: list[Mutation] = [
    Mutation(
        name="M1",
        description="UNKNOWN_SPDX default-deny → PASS",
        apply="m1",
    ),
    Mutation(
        name="M2",
        description="delete insightface/* from NC_MODEL_PATTERNS",
        apply="m2",
    ),
    Mutation(
        name="M3",
        description="NC_MODEL_IDS = frozenset()",
        apply="m3",
    ),
    Mutation(
        name="M4",
        description="_looks_like_research_source → exact frozenset membership",
        apply="m4",
    ),
    Mutation(
        name="M5",
        description="REQUIRED_MODEL_INGEST_DISPLAY_NAMES = ()",
        apply="m5",
    ),
]

_APPLIERS = {
    "m1": _m1_unknown_spdx_pass,
    "m2": _m2_drop_insightface_star,
    "m3": _m3_empty_nc_ids,
    "m4": _m4_exact_research_only,
    "m5": _m5_empty_required_names,
}


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
    # Point the test loader at the scratch policy via cwd layout:
    # scratch/train/occlusion/{license_policy,test_license_policy}.py
    env = dict(**{k: v for k, v in __import__("os").environ.items()})
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
        print("ERROR: license_policy.py / test_license_policy.py missing", file=sys.stderr)
        return 2

    selected = (
        MUTATIONS
        if args.mutation == "all"
        else [m for m in MUTATIONS if m.name == args.mutation]
    )

    survivors: list[str] = []
    killed: list[str] = []

    original = _POLICY.read_text(encoding="utf-8")

    for mutation in selected:
        with tempfile.TemporaryDirectory(prefix=f"licpol-{mutation.name}-") as tmp:
            base = Path(tmp)
            occ = _prepare_scratch(base)
            try:
                mutated = _apply_mutation(original, mutation)
            except RuntimeError as exc:
                print(f"ERROR applying {mutation.name}: {exc}", file=sys.stderr)
                return 2
            if mutated == original:
                print(f"ERROR {mutation.name}: mutation was a no-op", file=sys.stderr)
                return 2
            (occ / "license_policy.py").write_text(mutated, encoding="utf-8")
            rc, out = _run_suite(occ)
            summary = out.strip().splitlines()[-1] if out.strip() else "(no output)"
            if rc == 0:
                survivors.append(mutation.name)
                print(f"SURVIVED {mutation.name}: {mutation.description}")
                print(f"  suite: {summary}")
            else:
                killed.append(mutation.name)
                print(f"KILLED   {mutation.name}: {mutation.description}")
                print(f"  suite: {summary}")

    print()
    print(f"killed={len(killed)} survivors={len(survivors)} total={len(selected)}")
    if survivors:
        print("FAIL: mutants survived: " + ", ".join(survivors))
        return 1
    print("OK: all mutants killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
