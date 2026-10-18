"""Consumer regression for the planning tool's corpus location.

``benchmarks/tools/fir_corpus_population_draft_20260919.py`` must locate the
image corpus through the shared ``scripts.eval_harness.corpus_catalog`` resolver
and the tracked catalog, never through the stale ``images_root`` frozen inside
the v3r manifest. The resolver and catalog come from a separate producer; until
that producer joins, the integration checks fail with a named blocker instead of
skipping or standing in a fake resolver.

Each run executes the real tool with ``-I`` inside a temporary git checkout that
holds copies of the manifests, the mining report, the tracked catalog when it
exists, and a placeholder image directory. The ``-I`` flag forces the tool to
derive its own import root. No real pixels, aliases or private filenames are
read or printed.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = APP_DIR.parents[1]
TOOL = REPO_ROOT / "benchmarks/tools/fir_corpus_population_draft_20260919.py"
PRODUCER_REL = "apps/prototype-description-service/scripts/eval_harness/corpus_catalog.py"
CATALOG_REL = "benchmarks/manifests/corpus-catalog-v1.json"
MANIFEST_REL = "benchmarks/manifests/corpus-manifest-v3r-20260814.json"
MANIFEST_V3_REL = "benchmarks/manifests/corpus-manifest-v3.json"
CALIBRATION_REL = "benchmarks/manifests/slice-tag-calibration-v1.json"
MINING_REL = "benchmarks/reports/fir-occlusion-caption-mining-20260904.json"
PRIVATE_REL = "benchmarks/private/fir-capacity-20260919"
DRAFT_NAME = "fir-occ-population-review-draft-20260919.json"
SUMMARY_NAME = "fir-occ-population-review-summary-20260919.json"
PRIVATE_NAMES = sorted([DRAFT_NAME, "fir-occ-population-review-draft-20260919.csv", SUMMARY_NAME])

CORPUS_ID = "corpus646-originals"
MANIFEST_SHA256 = "2d9d5ba3e04bcfa7ea29f960b2fdc05431bdae7993bd22042a5369ceee7d9bff"
FROZEN_ENTRY = {
    "root_relative": "benchmarks/images/corpus646",
    "images_subdir": "originals",
    "provenance_file": "provenance.json",
    "manifest_path": MANIFEST_REL,
    "manifest_sha256": MANIFEST_SHA256,
    "hash_field": "sha256_source",
    "hash_space": "original",
}
NO_CLAIM_KEYS = (
    "pixel_identity_verified",
    "face_occlusion_verified",
    "person_sessions_verified",
    "sealed_confirmatory_test_eligible",
    "weight_training_authorized",
    "scored_observation_eligible_now",
)
# Pinned from the pre-change tool run on the frozen inputs; sampling must not move.
EXPECTED_COUNTS = {"records": 646, "personal_records": 591, "personal_unique_content": 588, "editorial_records": 55}
EXPECTED_ROLE_COUNTS = {
    "keyword_negative_frame": 489,
    "gallery_mate_review": 338,
    "quality_control_review": 56,
    "personal_frame": 588,
    "probability_review_pilot120": 120,
    "challenge_review_candidates": 106,
    "caption_failure_audit": 6,
    "keyword_negative_audit60": 60,
    "unknown_label_audit": 110,
    "zero_detection_audit": 40,
    "no_face_flag_audit": 37,
    "historical_golden150": 150,
    "editorial_research_only": 55,
}
EXPECTED_ROLE_IDS_SHA256 = "1744d6fbfdd8d493d121d3e6f897642efdea9af163b7871dccb4b0a7f45de542"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clean_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "user.name=consumer-test",
         "-c", "user.email=consumer-test@example.invalid", *args],
        cwd=cwd, env=_clean_env(), check=True, capture_output=True, text=True, timeout=120,
    )


def _run_tool(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(TOOL), *args],
        cwd=cwd, env=_clean_env(), capture_output=True, text=True, timeout=300,
    )


def _sandbox(root: Path, *, originals: bool) -> Path:
    """Temporary git checkout with copies of the tool inputs and no real image tree."""
    root.mkdir(parents=True, exist_ok=True)
    calibration = json.loads((REPO_ROOT / CALIBRATION_REL).read_text())
    inputs = [
        MANIFEST_REL,
        MANIFEST_V3_REL,
        CALIBRATION_REL,
        f"benchmarks/manifests/{calibration['detection_artifact']}",
        MINING_REL,
    ]
    if (REPO_ROOT / CATALOG_REL).is_file():
        inputs.append(CATALOG_REL)
    for rel in inputs:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REPO_ROOT / rel).read_bytes())
    if originals:
        images = root / "benchmarks/images/corpus646/originals"
        images.mkdir(parents=True)
        (images / "placeholder-0001.bin").write_bytes(b"synthetic placeholder bytes, not an image\n")
    _git(root, "init", "-q")
    return root


def _draft(root: Path) -> dict:
    return json.loads((root / PRIVATE_REL / DRAFT_NAME).read_text())


def _require_producer() -> None:
    """Named blocker until the separate producer joins; never skip, never stand in."""
    absent = [rel for rel in (PRODUCER_REL, CATALOG_REL) if not (REPO_ROOT / rel).is_file()]
    if absent:
        pytest.fail(
            "producer blocker, consumer integration RED until join; absent: " + ", ".join(absent),
            pytrace=False,
        )


def test_frozen_v3r_manifest_bytes_match_the_pinned_digest():
    assert _sha256(REPO_ROOT / MANIFEST_REL) == MANIFEST_SHA256


def test_producer_preflight_points_to_the_app_source():
    assert REPO_ROOT / PRODUCER_REL == (
        REPO_ROOT / "apps/prototype-description-service/scripts/eval_harness/corpus_catalog.py"
    )


def test_standalone_import_bootstrap_uses_app_source_from_unrelated_cwd(tmp_path):
    # Execute the real bootstrap up to the resolver import. This path regression
    # remains decisive before the separately committed resolver joins.
    code = """
import ast
import importlib.util
import sys
from pathlib import Path

tool = Path(sys.argv[1])
app = tool.parents[2] / 'apps/prototype-description-service'
tree = ast.parse(tool.read_text(), filename=str(tool))
boundary = next(i for i, node in enumerate(tree.body)
                if isinstance(node, ast.ImportFrom)
                and node.module == 'scripts.eval_harness.corpus_catalog')
bootstrap = ast.Module(body=tree.body[:boundary], type_ignores=[])
exec(compile(bootstrap, str(tool), 'exec'),
     {'__file__': str(tool), '__name__': 'bootstrap_probe'})
assert Path(sys.path[0]).resolve() == app.resolve(), sys.path[0]
spec = importlib.util.find_spec('scripts.eval_harness')
assert Path(spec.origin).resolve() == app / 'scripts/eval_harness/__init__.py'
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(TOOL)],
        cwd=tmp_path, env=_clean_env(), capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr


def test_producer_resolver_is_importable_from_repo_source(monkeypatch):
    _require_producer()
    monkeypatch.syspath_prepend(str(APP_DIR))
    module = importlib.import_module("scripts.eval_harness.corpus_catalog")
    assert Path(module.__file__).resolve() == (REPO_ROOT / PRODUCER_REL).resolve()
    assert issubclass(module.CatalogError, ValueError)
    assert callable(module.resolve_corpus)


def test_tracked_catalog_is_exactly_the_frozen_initial_entry():
    _require_producer()
    catalog = json.loads((REPO_ROOT / CATALOG_REL).read_text())
    assert set(catalog) == {"schema", "corpora"}
    assert catalog["schema"] == "benchmark-corpus-catalog/v1"
    assert catalog["corpora"] == {CORPUS_ID: FROZEN_ENTRY}


def test_metadata_route_reports_resolved_catalog_location(tmp_path):
    _require_producer()
    root = _sandbox(tmp_path / "primary", originals=True)
    result = _run_tool(root)
    assert result.returncode == 0, result.stderr
    draft = _draft(root)
    assert draft["current_source_root_exists"] is True
    assert draft["corpus_location"] == {
        "corpus_id": CORPUS_ID,
        "catalog_path": CATALOG_REL,
        "catalog_sha256": _sha256(REPO_ROOT / CATALOG_REL),
        "manifest_path": MANIFEST_REL,
        "manifest_sha256": MANIFEST_SHA256,
        "hash_field": "sha256_source",
        "hash_space": "original",
        "location_source": "primary_checkout",
    }


def test_absent_corpus_root_is_reported_absent_with_pinned_manifest(tmp_path):
    _require_producer()
    root = _sandbox(tmp_path / "primary", originals=False)
    result = _run_tool(root)
    assert result.returncode == 0, result.stderr
    draft = _draft(root)
    assert draft["current_source_root_exists"] is False
    assert draft["corpus_location"]["corpus_id"] == CORPUS_ID
    assert draft["corpus_location"]["manifest_path"] == MANIFEST_REL


def test_linked_worktree_reads_primary_checkout_corpus_root(tmp_path):
    _require_producer()
    primary = _sandbox(tmp_path / "primary", originals=True)
    _git(primary, "add", "benchmarks/manifests", "benchmarks/reports")
    _git(primary, "commit", "-q", "-m", "sandbox inputs")
    linked = tmp_path / "linked"
    _git(primary, "worktree", "add", "-q", "--detach", str(linked))
    result = _run_tool(linked)
    assert result.returncode == 0, result.stderr
    assert not (linked / "benchmarks/images").exists()
    draft = _draft(linked)
    assert draft["current_source_root_exists"] is True
    assert draft["corpus_location"]["location_source"] == "primary_checkout"


@pytest.mark.parametrize("defect", ["missing_catalog", "unknown_schema", "stale_images_root_key", "source_pin_mismatch"])
def test_bad_catalog_or_source_pin_fails_closed_without_private_outputs(tmp_path, defect):
    _require_producer()
    root = _sandbox(tmp_path / "primary", originals=True)
    catalog_path = root / CATALOG_REL
    if defect == "missing_catalog":
        catalog_path.unlink()
    else:
        catalog = json.loads(catalog_path.read_text())
        entry = catalog["corpora"][CORPUS_ID]
        if defect == "unknown_schema":
            catalog["schema"] = "benchmark-corpus-catalog/v0"
        elif defect == "stale_images_root_key":
            entry["images_root"] = "benchmarks/images/stale"
        else:
            entry["manifest_sha256"] = "0" * 64
        catalog_path.write_text(json.dumps(catalog, indent=2) + "\n")
    result = _run_tool(root)
    assert result.returncode == 2, result.stderr
    assert "Traceback" not in result.stderr
    assert not (root / PRIVATE_REL / DRAFT_NAME).exists()


def test_tool_source_never_reads_images_root_from_the_frozen_manifest():
    source = TOOL.read_text()
    assert re.findall(r"""\[\s*['"]images_root['"]\s*\]""", source) == []
    assert "resolve_corpus(" in source


def test_profile_calibration_route_passes_without_catalog_or_pixels(tmp_path):
    root = _sandbox(tmp_path / "primary", originals=False)
    (root / CATALOG_REL).unlink(missing_ok=True)
    result = _run_tool(root, "--check-profile-calibration")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "profile calibration and derived tags are consistent"
    assert not (root / "benchmarks/images").exists()
    assert not (root / "benchmarks/private").exists()


def test_sampling_roles_counts_and_private_outputs_are_unchanged(tmp_path):
    _require_producer()
    root = _sandbox(tmp_path / "primary", originals=True)
    result = _run_tool(root)
    assert result.returncode == 0, result.stderr
    assert sorted(p.name for p in (root / PRIVATE_REL).iterdir()) == PRIVATE_NAMES
    draft = _draft(root)
    summary = draft["summary"]
    assert draft["schema"] == "fir.corpus-population-review-draft.v1"
    assert draft["status"] == "PROVISIONAL_METADATA_REVIEW_LISTS_NOT_GOLD_NOT_EXECUTABLE_EVAL_SPLITS"
    assert [item["path"] for item in draft["inputs"]] == [MANIFEST_REL, MINING_REL]
    assert {key: summary[key] for key in EXPECTED_COUNTS} == EXPECTED_COUNTS
    assert summary["role_counts"] == EXPECTED_ROLE_COUNTS
    role_ids_digest = hashlib.sha256(json.dumps(summary["role_ids"], sort_keys=True).encode()).hexdigest()
    assert role_ids_digest == EXPECTED_ROLE_IDS_SHA256
    assert "Random(20260919)" in draft["method"]["probability_pilot"]
    assert "Random(20260920)" in draft["method"]["negative_audit"]
    assert [key for row in draft["entries"] for key in NO_CLAIM_KEYS if row[key] is not False] == []
