"""DESCQUAL-2 audit sampling: margin-of-error n, strata, inclusion probabilities."""

from __future__ import annotations

import ast
import json
import math
import random
import re
from collections.abc import Mapping
from pathlib import Path

import pytest

from scripts.eval_harness.audit_sampling import (
    Allocation,
    AuditSamplingError,
    ClusterSpec,
    DeffOrder,
    FramePsuPartition,
    allocate,
    design_effect,
    draw,
    draw_two_stage,
    estimate_icc,
    kish_effective_cluster_size,
    project_frame_psu_image_counts,
    project_strata_image_counts,
    project_strata_subject_image_counts,
    project_whole_frame_subject_image_counts,
    sample_size_for_margin,
    size_for_margin,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_FIR12_MANIFEST = _REPO_ROOT / "benchmarks/manifests/fir12-selection-v1.json"

# Real FIR-12 `strata_counts` shape (objects, not ints). Image N=640.
FIR12_STRATA_COUNTS: dict[str, dict[str, int]] = {
    "A_true_occluder": {"images": 32, "unique_subjects_faces_gt0": 20},
    "B_eyewear": {"images": 80, "unique_subjects_faces_gt0": 47},
    "C_pose": {"images": 34, "unique_subjects_faces_gt0": 15},
    "D_capture": {"images": 87, "unique_subjects_faces_gt0": 40},
    "E_clean": {"images": 407, "unique_subjects_faces_gt0": 109},
}

FIR12_IMAGE_N = {
    "A_true_occluder": 32,
    "B_eyewear": 80,
    "C_pose": 34,
    "D_capture": 87,
    "E_clean": 407,
}

def _entry(
    stratum: str, identities: list[str], media_id: int | str = 1
) -> dict[str, object]:
    return {
        "stratum": stratum,
        "present_identities": identities,
        "media_id": media_id,
    }


def _strata_counts() -> dict[str, dict[str, int]]:
    if not _FIR12_MANIFEST.is_file():
        return FIR12_STRATA_COUNTS
    payload = json.loads(_FIR12_MANIFEST.read_text())
    counts = payload["strata_counts"]
    if not isinstance(counts, dict):
        raise AuditSamplingError("fir12-selection-v1.json strata_counts is not an object")
    return counts


FIR12_STRATA = project_strata_image_counts(_strata_counts())

# Vendored FIR-12 frame: DESCQUAL-2 clone does not otherwise ship this JSON.
# Derived whole-frame Kish a (AUDIT-11); identities joined across strata.
def _fir12_entries() -> list[object]:
    if not _FIR12_MANIFEST.is_file():
        raise FileNotFoundError(
            f"vendored FIR-12 frame missing at {_FIR12_MANIFEST}"
        )
    payload = json.loads(_FIR12_MANIFEST.read_text())
    entries = payload["entries"]
    if not isinstance(entries, list) or not entries:
        raise AuditSamplingError("fir12-selection-v1.json entries must be a non-empty list")
    return entries


WHOLE_FRAME = project_whole_frame_subject_image_counts(_fir12_entries())
WHOLE_FRAME_KISH_A = kish_effective_cluster_size(WHOLE_FRAME.sizes)
FRAME_PSU = project_frame_psu_image_counts(_fir12_entries())
FRAME_PSU_KISH_A = kish_effective_cluster_size(FRAME_PSU.sizes)


def _members(sizes: dict[str, int] | None = None) -> dict[str, list[str]]:
    sizes = sizes or FIR12_STRATA
    return {name: [f"{name}-{i:03d}" for i in range(size)] for name, size in sizes.items()}


def test_sample_size_margin_10_on_640():
    assert sample_size_for_margin(margin=0.10, population=640) == 84


def test_sample_size_margin_15_on_640():
    assert sample_size_for_margin(margin=0.15, population=640) == 41


def test_sample_size_margin_05_on_640():
    assert sample_size_for_margin(margin=0.05, population=640) == 241


def test_sample_size_b_eyewear_precision_floor():
    # Proportional share of n=84 would give B ~10; that cannot carry a comparative claim.
    assert sample_size_for_margin(margin=0.10, population=80) == 44


def test_adapter_projects_images_from_real_strata_counts():
    counts = _strata_counts()
    sizes = project_strata_image_counts(counts)
    assert sizes == FIR12_IMAGE_N
    assert sum(sizes.values()) == 640
    assert sizes["A_true_occluder"] != counts["A_true_occluder"]["unique_subjects_faces_gt0"]


def test_adapter_rejects_int_valued_hand_frame():
    with pytest.raises(AuditSamplingError, match="object with 'images'"):
        project_strata_image_counts({"A": 32, "B": 80, "C": 34, "D": 87, "E": 407})


def test_allocate_rejects_unprojected_strata_counts():
    with pytest.raises(AuditSamplingError, match="project_strata_image_counts"):
        allocate(strata_sizes=FIR12_STRATA_COUNTS, n=84)  # type: ignore[arg-type]


def test_allocate_accepts_projected_real_frame():
    allocation = allocate(
        strata_sizes=project_strata_image_counts(_strata_counts()),
        n=84,
    )
    assert sum(allocation.values()) == 84
    assert set(allocation) == set(FIR12_IMAGE_N)


def test_kish_effective_cluster_size_is_not_the_mean():
    sizes = (1, 1, 4)
    assert kish_effective_cluster_size(sizes) == pytest.approx(3.0)
    assert sum(sizes) / len(sizes) == pytest.approx(2.0)
    assert kish_effective_cluster_size(sizes) != pytest.approx(sum(sizes) / len(sizes))
    assert kish_effective_cluster_size((3, 3, 3)) == pytest.approx(3.0)


def test_whole_frame_join_merges_identity_across_strata():
    entries = [
        _entry("A_true_occluder", ["alice"]),
        _entry("B_eyewear", ["alice"]),
        _entry("B_eyewear", ["bob"]),
    ]
    frame = project_whole_frame_subject_image_counts(entries)
    assert sorted(frame.sizes) == [1, 2]
    assert kish_effective_cluster_size(frame.sizes) == pytest.approx(5 / 3)
    concat = [
        m
        for v in project_strata_subject_image_counts(entries).values()
        for m in v
    ]
    assert sorted(concat) == [1, 1, 1]
    assert kish_effective_cluster_size(concat) == pytest.approx(1.0)


def test_whole_frame_counts_unlabeled_and_multi_identity_images():
    entries = [
        _entry("E_clean", []),
        _entry("E_clean", []),
        _entry("B_eyewear", ["alice", "bob"]),
        _entry("C_pose", ["alice", "bob", "cara"]),
        _entry("D_capture", ["dana"]),
    ]
    frame = project_whole_frame_subject_image_counts(entries)
    assert frame.n_entries == 5
    assert frame.n_unlabeled == 2
    assert frame.n_multi_identity_images == 2
    assert frame.extra_memberships == 3
    assert sorted(frame.sizes) == [1, 1, 2, 2]


def test_whole_frame_kish_a_joins_identities_across_strata():
    entries = json.loads(_FIR12_MANIFEST.read_text())["entries"]
    assert len(entries) == 640
    frame = project_whole_frame_subject_image_counts(entries)
    assert frame.n_entries == 640
    assert len(frame.sizes) == 130
    assert sum(frame.sizes) == 544
    assert sum(m * m for m in frame.sizes) == 7020
    assert sum(m * (m - 1) for m in frame.sizes) == 6476
    assert frame.n_unlabeled == 115
    assert frame.n_multi_identity_images == 16
    assert frame.extra_memberships == 19
    a = kish_effective_cluster_size(frame.sizes)
    assert a == pytest.approx(7020 / 544)
    assert a == pytest.approx(12.904412, abs=1e-6)
    assert WHOLE_FRAME_KISH_A == pytest.approx(a)

    # The obvious composition splits a subject who appears in two strata
    # into two clusters and understates deff (a = 7.41 over 231 clusters).
    per_stratum = project_strata_subject_image_counts(entries)
    concat = [m for v in per_stratum.values() for m in v]
    assert len(concat) == 231
    split_a = kish_effective_cluster_size(concat)
    assert split_a == pytest.approx(7.408088, rel=1e-6)
    assert split_a < a


def test_frame_psu_partition_assigns_first_listed_or_unlabeled_singleton():
    entries = [
        _entry("E_clean", ["alice", "bob"], media_id=1),
        _entry("B_eyewear", ["alice"], media_id=2),
        _entry("C_pose", ["cara", "bob"], media_id=3),
        _entry("E_clean", [], media_id=99),
        _entry("D_capture", ["dana", "erin"], media_id=4),
    ]
    part = project_frame_psu_image_counts(entries)
    # alice: 2, cara: 1, dana: 1, unlabeled:99: 1. bob and erin are never first.
    assert sorted(part.sizes) == [1, 1, 1, 2]
    assert part.n_entries == 5
    assert part.n_psus == 4
    assert sum(part.sizes) == part.n_entries
    assert part.n_unlabeled_singletons == 1
    assert part.never_first_identities == ("bob", "erin")


def test_frame_psu_partition_requires_sizes_sum_to_n_entries():
    with pytest.raises(AuditSamplingError, match="partition"):
        FramePsuPartition(
            sizes=(1, 2, 3),
            n_entries=7,
            n_psus=3,
            n_unlabeled_singletons=0,
            never_first_identities=(),
        )


def test_frame_psu_partition_requires_media_id():
    with pytest.raises(AuditSamplingError, match="media_id"):
        project_frame_psu_image_counts(
            [{"stratum": "E_clean", "present_identities": []}]
        )
    with pytest.raises(AuditSamplingError, match="media_id"):
        project_frame_psu_image_counts(
            [{"stratum": "E_clean", "present_identities": ["alice"], "media_id": ""}]
        )
    with pytest.raises(AuditSamplingError, match="media_id"):
        project_frame_psu_image_counts(
            [{"stratum": "E_clean", "present_identities": ["alice"], "media_id": True}]
        )


def test_frame_psu_kish_a_is_partition_of_640():
    entries = json.loads(_FIR12_MANIFEST.read_text())["entries"]
    part = project_frame_psu_image_counts(entries)
    assert part.n_entries == 640
    assert part.n_psus == 241
    assert len(part.sizes) == 241
    assert sum(part.sizes) == 640
    assert sum(m * m for m in part.sizes) == 6942
    assert part.n_unlabeled_singletons == 115
    assert part.never_first_identities == (
        "Auburn Hollow",
        "Tidal Quarry",
        "Vellum Warren",
        "Verdant Beacon",
    )
    a = kish_effective_cluster_size(part.sizes)
    assert a == pytest.approx(6942 / 640)
    assert a == pytest.approx(10.846875)
    assert FRAME_PSU_KISH_A == pytest.approx(a)
    assert FRAME_PSU.n_psus == 241
    # Labeled-subject a is still the overlapping 130-vector (BR-18 / diagnostic).
    assert WHOLE_FRAME_KISH_A == pytest.approx(12.904412, abs=1e-6)
    assert FRAME_PSU_KISH_A != pytest.approx(WHOLE_FRAME_KISH_A)


@pytest.mark.parametrize(
    ("icc", "n", "deff"),
    [
        (0.0, 84, 1.000),
        (0.05, 118, 1.492),
        (0.1, 148, 1.985),
        (0.2, 198, 2.969),
        (0.3, 239, 3.954),
        (0.5, 302, 5.923),
    ],
)
def test_planning_n_on_frame_psu_kish_a(icc: float, n: int, deff: float):
    record = size_for_margin(
        margin=0.10, population=640, cluster_size=FRAME_PSU_KISH_A, icc=icc
    )
    assert record.n == n
    assert round(record.deff, 3) == deff
    assert record.deff == pytest.approx(1.0 + (FRAME_PSU_KISH_A - 1.0) * icc)
    assert record.cluster_size == FRAME_PSU_KISH_A


def test_kish_effective_cluster_size_rejects_empty_and_non_positive():
    with pytest.raises(AuditSamplingError, match="non-empty"):
        kish_effective_cluster_size(())
    with pytest.raises(AuditSamplingError, match="finite number > 0"):
        kish_effective_cluster_size((1, 0))
    with pytest.raises(AuditSamplingError, match="finite number > 0"):
        kish_effective_cluster_size((1, -2))
    with pytest.raises(AuditSamplingError, match="finite number > 0"):
        kish_effective_cluster_size((1, float("nan")))
    with pytest.raises(AuditSamplingError, match="finite number > 0"):
        kish_effective_cluster_size((1, float("inf")))


def test_design_effect_kish_effective_size():
    assert design_effect(cluster_size=WHOLE_FRAME_KISH_A, icc=0.2) == pytest.approx(
        1.0 + (WHOLE_FRAME_KISH_A - 1.0) * 0.2
    )


def test_deff_then_fpc_ordering_on_labeled_subject_a_not_planning_n():
    # Ordering pin only: deff-then-fpc (216) vs the wrong fpc-then-deff (284).
    # cluster_size is the labeled-subject a (WHOLE_FRAME_KISH_A, Σm=544 over
    # 130 overlapping identities). That vector is not a PSU partition of the
    # 640-image frame. Planning n uses FRAME_PSU_KISH_A → 198, not 216.
    record = size_for_margin(
        margin=0.10, population=640, cluster_size=WHOLE_FRAME_KISH_A, icc=0.2
    )
    assert record.n == 216
    assert record.deff_order is DeffOrder.DEFF_THEN_FPC
    assert record.deff_order == "deff_then_fpc"
    assert record.cluster_size == WHOLE_FRAME_KISH_A
    assert record.cluster_size != FRAME_PSU_KISH_A
    assert record.icc == 0.2
    assert record.deff == pytest.approx(1.0 + (WHOLE_FRAME_KISH_A - 1.0) * 0.2)
    assert record.n_deff == pytest.approx(record.n0 * record.deff)
    expected = math.ceil(record.n_deff / (1.0 + (record.n_deff - 1.0) / 640))
    assert record.n == expected == 216
    old_order = math.ceil(sample_size_for_margin(margin=0.10, population=640) * record.deff)
    assert old_order == 284
    assert record.n != old_order
    # Mean of the cluster vector is Σm / 130 = 544/130 ≈ 4.18, not 640/130 = 4.92
    # (that puts the 115 unlabeled images in the numerator).
    mean_m = sum(WHOLE_FRAME.sizes) / len(WHOLE_FRAME.sizes)
    assert mean_m == pytest.approx(544 / 130)
    mean_n = size_for_margin(margin=0.10, population=640, cluster_size=mean_m, icc=0.2).n
    assert mean_n == 127
    assert record.n - mean_n == 89
    planning = size_for_margin(
        margin=0.10, population=640, cluster_size=FRAME_PSU_KISH_A, icc=0.2
    )
    assert planning.n == 198
    assert planning.n != record.n


_SCOPE_DOC = _REPO_ROOT / "docs/scopes/descqual-2-fact-annotation-pilot.md"

_TRAILING_COMMENT = re.compile(r"^(.*?)\s+#\s*(.*)$")
_FENCE_LANG_TAG = re.compile(r"^[A-Za-z][\w+-]*$")
_AUDIT_SKIP_TOKEN = "audit-skip"
_PSU_CENSUS_COMMENT = re.compile(
    r"^(?P<n_psus>\d+)\s+PSUs,\s*"
    r"(?:Σm|Sm)\s*=\s*(?P<sum_m>\d+),\s*"
    r"(?:Σm²|Σm2|Sm2)\s*=\s*(?P<sum_m2>\d+)\s*$"
)


def _parse_fence_block(block: str) -> tuple[str, frozenset[str], str]:
    """Return (lang, info_tokens, source). Unknown/absent tags are not a skip."""
    if "\n" not in block:
        info = block.strip()
        tokens = tuple(info.split()) if info else ()
        if tokens and _FENCE_LANG_TAG.fullmatch(tokens[0]):
            lowered = tuple(token.lower() for token in tokens)
            return lowered[0], frozenset(lowered), ""
        return "", frozenset(), block
    first, rest = block.split("\n", 1)
    info = first.strip()
    tokens = tuple(info.split()) if info else ()
    if tokens and _FENCE_LANG_TAG.fullmatch(tokens[0]):
        lowered = tuple(token.lower() for token in tokens)
        return lowered[0], frozenset(lowered), rest
    return "", frozenset(), block


def _fence_is_opted_out(tokens: frozenset[str]) -> bool:
    return _AUDIT_SKIP_TOKEN in tokens


def _block_has_audit_skip(block: str) -> bool:
    info = block.split("\n", 1)[0].strip()
    return _AUDIT_SKIP_TOKEN in {token.lower() for token in info.split()}


# BR-57: CommonMark fences are 3+ ` or ~; a closer must match the opener
# character and length. split("```") is blind to ~~~ and a second
# split("~~~") would cut a backtick fence whose body contains tildes.
_OPENING_FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")
_CLOSING_FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})[ \t]*$")


def _opening_fence(line: str) -> tuple[str, int, str] | None:
    match = _OPENING_FENCE.fullmatch(line)
    if match is None:
        return None
    marker, info = match.group(2), match.group(3)
    char = marker[0]
    if char == "`" and "`" in info:
        return None
    return char, len(marker), info


def _closing_fence(line: str, char: str, length: int) -> bool:
    match = _CLOSING_FENCE.fullmatch(line)
    if match is None:
        return False
    marker = match.group(2)
    return marker[0] == char and len(marker) >= length


def _scope_doc_fence_blocks(text: str) -> list[str]:
    lines = text.splitlines(keepends=True)
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        opened = _opening_fence(lines[index].rstrip("\r\n"))
        if opened is None:
            index += 1
            continue
        char, length, info = opened
        body_parts: list[str] = []
        index += 1
        while index < len(lines):
            if _closing_fence(lines[index].rstrip("\r\n"), char, length):
                index += 1
                break
            body_parts.append(lines[index])
            index += 1
        blocks.append(info + "\n" + "".join(body_parts))
    return blocks


def _fence_containing(text: str, needle: str) -> str:
    for block in _scope_doc_fence_blocks(text):
        if needle in block:
            return block.strip()
    raise AssertionError(f"no fenced block contains {needle!r}")


def _iter_unfenced_lines(text: str) -> list[str]:
    lines = text.splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        opened = _opening_fence(lines[index])
        if opened is None:
            out.append(lines[index])
            index += 1
            continue
        char, length, _info = opened
        index += 1
        while index < len(lines):
            if _closing_fence(lines[index], char, length):
                index += 1
                break
            index += 1
    return out


def _scope_doc_executable_fences(text: str) -> list[str]:
    # BR-44: check every fence; skip only an explicit audit-skip token.
    fences: list[str] = []
    for block in _scope_doc_fence_blocks(text):
        _lang, tokens, source = _parse_fence_block(block)
        if _fence_is_opted_out(tokens):
            continue
        stripped = source.strip()
        if stripped:
            fences.append(stripped)
    return fences


def _exec_scope_fence(
    block: str, monkeypatch: pytest.MonkeyPatch
) -> dict[str, object]:
    monkeypatch.chdir(_REPO_ROOT)
    monkeypatch.syspath_prepend(str(_REPO_ROOT / "apps/prototype-description-service"))
    namespace: dict[str, object] = {}
    exec(compile(block, str(_SCOPE_DOC), "exec"), namespace)
    return namespace


def _published_literal(comment: str) -> object | None:
    text = comment.strip()
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        pass
    stripped = re.sub(r"\s*\([^)]*\)\s*$", "", text).strip()
    if stripped == text:
        return None
    try:
        return ast.literal_eval(stripped)
    except (ValueError, SyntaxError):
        return None


def _eval_fence_line(line: str, namespace: dict[str, object]) -> object:
    tree = ast.parse(line, mode="exec")
    if len(tree.body) != 1:
        raise AssertionError(f"expected a single statement, got {line!r}")
    stmt = tree.body[0]
    if isinstance(stmt, ast.Assign):
        value = stmt.value
    elif isinstance(stmt, ast.Expr):
        value = stmt.value
    else:
        raise AssertionError(f"fence line is not an assignment or expression: {line}")
    return eval(compile(ast.Expression(value), str(_SCOPE_DOC), "eval"), namespace)


def _assert_published_matches(
    computed: object, published: object, expr: str, *, source: str = "fence"
) -> None:
    message = (
        f"{source} publishes {published!r} for {expr!r} but eval returned {computed!r}"
    )
    if isinstance(published, dict):
        actual: object = dict(computed) if isinstance(computed, Mapping) else computed
        assert actual == published, message
        return
    if (
        isinstance(published, (int, float))
        and not isinstance(published, bool)
        and isinstance(computed, (int, float))
        and not isinstance(computed, bool)
    ):
        assert computed == pytest.approx(published), message
        return
    assert computed == published, message


def _comment_is_opted_out(comment: str) -> bool:
    return comment.strip().lower() == _AUDIT_SKIP_TOKEN


def _assert_psu_census_comment_matches(
    computed: object,
    published_n_psus: int,
    published_sum_m: int,
    published_sum_m2: int,
    expr: str,
) -> None:
    if not isinstance(computed, FramePsuPartition):
        raise AssertionError(
            f"PSU census comment on {expr!r} but eval returned {computed!r}"
        )
    actual_sum = sum(computed.sizes)
    actual_sum_sq = sum(m * m for m in computed.sizes)
    message = (
        f"fence publishes {published_n_psus} PSUs, Σm={published_sum_m}, "
        f"Σm²={published_sum_m2} for {expr!r} but eval returned "
        f"n_psus={computed.n_psus}, Σm={actual_sum}, Σm²={actual_sum_sq}"
    )
    assert computed.n_psus == published_n_psus, message
    assert actual_sum == published_sum_m, message
    assert actual_sum_sq == published_sum_m2, message


def _assert_fence_published_comments_match_eval(
    block: str, namespace: dict[str, object]
) -> None:
    # BR-31 / BR-34 / BR-45: pin every trailing comment; unparseable is a fail.
    pinned = 0
    for raw in block.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _TRAILING_COMMENT.fullmatch(line)
        if "size_for_margin(" in line:
            assert match is not None, (
                f"size_for_margin line has no trailing published comment: {line}"
            )
            assert _published_literal(match.group(2)) is not None, (
                f"size_for_margin line comment is not a published literal: {line}"
            )
        if match is None:
            continue
        expr, comment = match.group(1), match.group(2)
        if _comment_is_opted_out(comment):
            continue
        census = _PSU_CENSUS_COMMENT.fullmatch(comment.strip())
        computed = _eval_fence_line(expr, namespace)
        if census is not None:
            _assert_psu_census_comment_matches(
                computed,
                int(census.group("n_psus")),
                int(census.group("sum_m")),
                int(census.group("sum_m2")),
                expr,
            )
            pinned += 1
            continue
        published = _published_literal(comment)
        if published is None:
            raise AssertionError(
                "unparseable trailing comment inside collected fence "
                f"(not a published literal, not a PSU census, not {_AUDIT_SKIP_TOKEN}): "
                f"{line}"
            )
        _assert_published_matches(computed, published, expr)
        pinned += 1
    assert pinned > 0, "fence has no published trailing comments to pin"


# BR-58: planning n/deff live in GFM tables, not only in fences. Scope to
# the two sample-size tables (target-margin→n, and ICC/deff/n); other
# pipe tables are ignored.
_MARGIN_PP = re.compile(r"^±\s*(?P<pp>\d+(?:\.\d+)?)\s*pp$")
_HEADER_A = re.compile(r"\ba\s*=\s*([0-9]+(?:\.[0-9]+)?)")
_HEADER_POPULATION = re.compile(r"\bN\s*=\s*(\d+)")
_HEADER_MARGIN_PP = re.compile(r"±\s*(\d+(?:\.\d+)?)\s*pp")
_HTML_COMMENT = re.compile(r"<!--.*?-->", flags=re.DOTALL)

# This scope document intentionally has four executable Python fences. Keep an
# exact inventory so an indented/nested fence cannot silently leave a published
# calculation outside the audit. The snippets are stable anchors, rather than
# line numbers, because prose edits should not invalidate the guard.
_EXPECTED_EXECUTABLE_FENCE_NEEDLES = (
    "allocate(strata_sizes=project_strata_image_counts(strata_counts), n=84)",
    "frame = project_frame_psu_image_counts(entries)   # 241 PSUs",
    "sum_m_m_minus_1 = sum(m * (m - 1) for m in frame.sizes)",
    "size_for_margin(margin=0.10, population=640, cluster_size=a, icc=0.044).n  # 114",
)
_EXPECTED_MARGIN_TABLE_ROWS = 4
_EXPECTED_ICC_TABLE_ROWS = 6
# Published ``n=...`` prose is an operator-facing quantity as well as a table
# cell. Keep a multiset (rather than only a set) so changing one occurrence to
# another already-known value cannot preserve a deceptively green inventory.
_EXPECTED_PUBLISHED_N_VALUES = (
    84,
    84,
    147,
    198,
    198,
    198,
    239,
    239,
    327,
)


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _is_separator_row(line: str) -> bool:
    if not _is_table_row(line):
        return False
    cells = _split_table_row(line)
    if not cells:
        return False
    return all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def _markdown_tables_outside_fences(text: str) -> list[tuple[list[str], list[list[str]]]]:
    lines = _iter_unfenced_lines(text)
    tables: list[tuple[list[str], list[list[str]]]] = []
    index = 0
    while index < len(lines) - 1:
        if not _is_table_row(lines[index]) or not _is_separator_row(lines[index + 1]):
            index += 1
            continue
        header = _split_table_row(lines[index])
        index += 2
        rows: list[list[str]] = []
        while (
            index < len(lines)
            and _is_table_row(lines[index])
            and not _is_separator_row(lines[index])
        ):
            rows.append(_split_table_row(lines[index]))
            index += 1
        tables.append((header, rows))
    return tables


def _header_cell_norm(cell: str) -> str:
    return re.sub(r"\s+", " ", cell.replace("**", "").strip().lower())


def _is_margin_n_table(norms: list[str]) -> bool:
    return any("target margin" in cell for cell in norms) and any(
        cell == "n" or cell.startswith("n ") for cell in norms
    )


def _is_icc_deff_n_table(norms: list[str]) -> bool:
    return any(cell == "icc" for cell in norms) and any(
        cell == "deff" or cell.startswith("deff ") for cell in norms
    )


def _header_index(norms: list[str], predicate, label: str) -> int:
    matches = [index for index, cell in enumerate(norms) if predicate(cell)]
    if not matches:
        raise AssertionError(f"audited table header missing {label} column: {norms}")
    assert len(matches) == 1, (
        f"audited table header has duplicate {label} columns: {norms}"
    )
    return matches[0]


def _cell_literal(cell: str) -> object | None:
    return _published_literal(cell.replace("**", "").strip())


def _cell_margin(cell: str) -> float:
    text = cell.replace("**", "").strip()
    match = _MARGIN_PP.fullmatch(text)
    if match is None:
        raise AssertionError(f"table margin cell is not ±N pp: {cell!r}")
    return float(match.group("pp")) / 100.0


def _require_number(value: object, cell: str, label: str) -> int | float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise AssertionError(f"table {label} cell is not a published number: {cell!r}")
    return value


def _eval_frame_n_and_a() -> tuple[int, float]:
    frame = project_frame_psu_image_counts(_fir12_entries())
    return frame.n_entries, kish_effective_cluster_size(frame.sizes)


def _assert_header_published_frame_params(
    header: list[str], a: float, population: int
) -> None:
    joined = " ".join(header)
    a_match = _HEADER_A.search(joined)
    if a_match is not None:
        published_a = ast.literal_eval(a_match.group(1))
        _assert_published_matches(
            a,
            published_a,
            "kish_effective_cluster_size(frame.sizes)",
            source="table",
        )
    pop_match = _HEADER_POPULATION.search(joined)
    if pop_match is not None:
        published_pop = int(pop_match.group(1))
        _assert_published_matches(
            population, published_pop, "frame.n_entries", source="table"
        )


def _assert_margin_n_table(
    header: list[str], rows: list[list[str]], population: int
) -> None:
    norms = [_header_cell_norm(cell) for cell in header]
    margin_i = _header_index(norms, lambda cell: "target margin" in cell, "target margin")
    n_i = _header_index(
        norms, lambda cell: cell == "n" or cell.startswith("n "), "n"
    )
    assert len(rows) == _EXPECTED_MARGIN_TABLE_ROWS, (
        "target-margin table must contain all four published margin rows; "
        f"found {len(rows)}"
    )
    for row in rows:
        if len(row) != len(header):
            raise AssertionError(
                f"target-margin table row has {len(row)} cells; "
                f"expected {len(header)}: {row!r}"
            )
        margin = _cell_margin(row[margin_i])
        published_n = _require_number(_cell_literal(row[n_i]), row[n_i], "n")
        computed = sample_size_for_margin(margin=margin, population=population)
        _assert_published_matches(
            computed,
            published_n,
            f"sample_size_for_margin(margin={margin}, population={population})",
            source="table",
        )


def _assert_icc_deff_n_table(
    header: list[str],
    rows: list[list[str]],
    population: int,
    a: float,
) -> None:
    norms = [_header_cell_norm(cell) for cell in header]
    icc_i = _header_index(norms, lambda cell: cell == "icc", "ICC")
    deff_i = _header_index(
        norms, lambda cell: cell == "deff" or cell.startswith("deff "), "deff"
    )
    n_i = _header_index(
        norms, lambda cell: cell == "n" or cell.startswith("n "), "n"
    )
    _assert_header_published_frame_params(header, a, population)
    joined = " ".join(header)
    margin_match = _HEADER_MARGIN_PP.search(joined)
    margin = float(margin_match.group(1)) / 100.0 if margin_match is not None else 0.10
    assert len(rows) == _EXPECTED_ICC_TABLE_ROWS, (
        "ICC/deff/n table must contain all six published ICC rows; "
        f"found {len(rows)}"
    )
    for row in rows:
        if len(row) != len(header):
            raise AssertionError(
                f"ICC/deff/n table row has {len(row)} cells; "
                f"expected {len(header)}: {row!r}"
            )
        icc = float(
            _require_number(_cell_literal(row[icc_i]), row[icc_i], "ICC")
        )
        published_deff = _require_number(
            _cell_literal(row[deff_i]), row[deff_i], "deff"
        )
        published_n = _require_number(_cell_literal(row[n_i]), row[n_i], "n")
        record = size_for_margin(
            margin=margin, population=population, cluster_size=a, icc=icc
        )
        _assert_published_matches(
            round(record.deff, 3),
            published_deff,
            f"round(design_effect(cluster_size=a, icc={icc}), 3)",
            source="table",
        )
        _assert_published_matches(
            record.n,
            published_n,
            (
                "size_for_margin("
                f"margin={margin}, population={population}, cluster_size=a, icc={icc}).n"
            ),
            source="table",
        )


def _assert_scope_doc_published_tables_match_eval(path: Path = _SCOPE_DOC) -> None:
    text = _HTML_COMMENT.sub("", path.read_text())
    population, a = _eval_frame_n_and_a()
    audited = 0
    for header, rows in _markdown_tables_outside_fences(text):
        norms = [_header_cell_norm(cell) for cell in header]
        if _is_margin_n_table(norms):
            _assert_margin_n_table(header, rows, population)
            audited += 1
        elif _is_icc_deff_n_table(norms):
            _assert_icc_deff_n_table(header, rows, population, a)
            audited += 1
    assert audited >= 2, (
        "scope doc has no target-margin or ICC/deff/n tables to pin "
        f"(found {audited} audited tables)"
    )


def _assert_scope_doc_fence_inventory(text: str) -> None:
    fences = _scope_doc_executable_fences(text)
    assert len(fences) == len(_EXPECTED_EXECUTABLE_FENCE_NEEDLES), (
        "scope doc executable fence inventory changed: "
        f"expected {len(_EXPECTED_EXECUTABLE_FENCE_NEEDLES)}, found {len(fences)}"
    )
    for needle in _EXPECTED_EXECUTABLE_FENCE_NEEDLES:
        matches = [block for block in fences if needle in block]
        assert len(matches) == 1, (
            f"scope doc executable fence inventory missing or duplicated {needle!r}"
        )


def _assert_scope_doc_success_criteria_numbers(text: str) -> None:
    # The tables and code fences cover calculations, while this sentence is
    # the human-facing decision record. Strip comments so hidden HTML cannot
    # satisfy it, then pin both planning and sensitivity n values.
    visible = _HTML_COMMENT.sub("", text)
    normalized = re.sub(r"\s+", " ", visible)
    expected = re.compile(
        r"Full-sample n is the pre-registered planning value "
        r"\*\*n = 198\*\* at ICC=0\.20 .*?"
        r"sensitivity \*\*n = 239\*\* at ICC=0\.30"
    )
    assert expected.search(normalized), (
        "scope doc success criteria lost the published planning/sensitivity n values"
    )


def _assert_scope_doc_published_n_inventory(text: str) -> None:
    """Pin every visible ``n=...`` token, including prose outside containers.

    Tables and executable fences have structural checks above, but a reviewer
    can still copy a wrong sample size into narrative text or an HTML comment
    without touching either container. Strip comments first, then compare the
    complete multiset for this document's explicit ``n=`` claims.
    """
    visible = _HTML_COMMENT.sub("", text)
    observed = tuple(
        sorted(int(match.group("value")) for match in re.finditer(
            r"\bn\s*=\s*(?P<value>\d+)\b", visible
        ))
    )
    assert observed == tuple(sorted(_EXPECTED_PUBLISHED_N_VALUES)), (
        "scope doc visible n= quantity inventory changed: "
        f"expected={sorted(_EXPECTED_PUBLISHED_N_VALUES)} observed={list(observed)}"
    )


def _assert_all_executable_fences_match_eval(
    text: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    fences = _scope_doc_executable_fences(text)
    assert fences, "scope doc has no executable fences to pin"
    for block in fences:
        namespace = _exec_scope_fence(block, monkeypatch)
        _assert_fence_published_comments_match_eval(block, namespace)


def test_published_cells_regenerate_from_fir12_selection_manifest():
    # BR-30: published n must come from the frozen frame through shipped
    # projectors, not a test-module Kish-a name.
    entries = json.loads(_FIR12_MANIFEST.read_text())["entries"]
    frame = project_frame_psu_image_counts(entries)
    a = kish_effective_cluster_size(frame.sizes)
    assert _FIR12_MANIFEST.name == "fir12-selection-v1.json"
    assert frame.n_entries == 640
    assert a == pytest.approx(10.846875)
    assert size_for_margin(margin=0.10, population=640, cluster_size=a, icc=0.044).n == 114
    assert size_for_margin(margin=0.10, population=640, cluster_size=a, icc=0.361).n == 261
    assert size_for_margin(margin=0.10, population=640, cluster_size=a, icc=0.2).n == 198
    assert size_for_margin(margin=0.10, population=640, cluster_size=a, icc=0.3).n == 239
    assert size_for_margin(margin=0.10, population=640, cluster_size=a, icc=1.0).n == 397
    b_entries = [e for e in entries if e["stratum"] == "B_eyewear"]
    b_a = kish_effective_cluster_size(project_frame_psu_image_counts(b_entries).sizes)
    assert size_for_margin(margin=0.10, population=80, cluster_size=b_a, icc=0.2).n == 48


def test_scope_doc_ci_n_fence_runs_as_written(monkeypatch: pytest.MonkeyPatch):
    doc = _SCOPE_DOC.read_text()
    assert "FRAME_PSU_KISH_A" not in doc
    assert "WHOLE_FRAME_KISH_A" not in doc
    block = _fence_containing(doc, "icc=0.044")
    assert "benchmarks/manifests/fir12-selection-v1.json" in block
    assert "project_frame_psu_image_counts" in block
    assert "kish_effective_cluster_size" in block
    assert "size_for_margin" in block
    assert "cluster_size=a" in block
    namespace = _exec_scope_fence(block, monkeypatch)
    a = namespace["a"]
    assert isinstance(a, float)
    assert a == pytest.approx(10.846875)
    _assert_fence_published_comments_match_eval(block, namespace)


def test_scope_doc_planning_n_fence_runs_as_written(monkeypatch: pytest.MonkeyPatch):
    doc = _SCOPE_DOC.read_text()
    block = _fence_containing(doc, "cluster_size=b_a")
    assert "cluster_size=2.1" not in block
    assert "benchmarks/manifests/fir12-selection-v1.json" in block
    assert "project_frame_psu_image_counts" in block
    assert "kish_effective_cluster_size" in block
    assert "size_for_margin" in block
    assert "cluster_size=a" in block
    assert "icc=0.2" in block
    assert "icc=0.3" in block
    namespace = _exec_scope_fence(block, monkeypatch)
    a = namespace["a"]
    assert isinstance(a, float)
    assert a == pytest.approx(10.846875)
    b_a = namespace["b_a"]
    assert isinstance(b_a, float)
    assert b_a == pytest.approx(2.1)
    assert size_for_margin(margin=0.10, population=80, cluster_size=b_a, icc=0.2).n == 48
    _assert_fence_published_comments_match_eval(block, namespace)


def test_every_scope_doc_executable_fence_published_comment_matches_eval(
    monkeypatch: pytest.MonkeyPatch,
):
    doc = _SCOPE_DOC.read_text()
    _assert_scope_doc_fence_inventory(doc)
    fences = _scope_doc_executable_fences(doc)
    raw_fences = _scope_doc_fence_blocks(doc)
    opted_out = [block for block in raw_fences if _block_has_audit_skip(block)]
    assert opted_out, "display-math fences must be explicitly opted out with audit-skip"
    assert len(fences) == len(raw_fences) - len(opted_out)
    _assert_all_executable_fences_match_eval(doc, monkeypatch)


def test_scope_doc_fence_collector_count_is_all_fences_minus_opt_outs():
    doc = _SCOPE_DOC.read_text()
    _assert_scope_doc_fence_inventory(doc)
    raw_fences = _scope_doc_fence_blocks(doc)
    opted_out = [block for block in raw_fences if _block_has_audit_skip(block)]
    collected = _scope_doc_executable_fences(doc)
    assert raw_fences, "scope doc has no fenced blocks"
    assert len(collected) == len(raw_fences) - len(opted_out)
    assert len(opted_out) == 1
    assert all(_AUDIT_SKIP_TOKEN in _parse_fence_block(block)[1] for block in opted_out)


def test_scope_doc_fence_collector_keeps_unknown_and_non_python_tags():
    sample = (
        "intro\n"
        "```\nuntagged  # 1\n```\n"
        "```python3\npython3_tagged  # 2\n```\n"
        "```text\ntext_tagged  # 3\n```\n"
        "```text audit-skip\nopted_out  # 4\n```\n"
        "```rs\nrust_tagged  # 5\n```\n"
    )
    raw_fences = _scope_doc_fence_blocks(sample)
    opted_out = [block for block in raw_fences if _block_has_audit_skip(block)]
    collected = _scope_doc_executable_fences(sample)
    assert len(raw_fences) == 5
    assert len(opted_out) == 1
    assert len(collected) == len(raw_fences) - len(opted_out) == 4
    joined = "\n".join(collected)
    assert "untagged" in joined
    assert "python3_tagged" in joined
    assert "text_tagged" in joined
    assert "rust_tagged" in joined
    assert "opted_out" not in joined


def test_unparseable_trailing_comment_fails_instead_of_skipping():
    with pytest.raises(AssertionError, match="unparseable trailing comment"):
        _assert_fence_published_comments_match_eval("x = 1  # not-a-literal", {"x": 1})


def test_psu_census_trailing_comment_is_checked():
    namespace = {
        "project_frame_psu_image_counts": project_frame_psu_image_counts,
        "entries": _fir12_entries(),
    }
    truth = "frame = project_frame_psu_image_counts(entries)  # 241 PSUs, Σm=640, Σm²=6942"
    _assert_fence_published_comments_match_eval(truth, namespace)
    lie = "frame = project_frame_psu_image_counts(entries)  # 999 PSUs, Σm=640, Σm²=6942"
    with pytest.raises(AssertionError, match="999"):
        _assert_fence_published_comments_match_eval(lie, namespace)


def test_scope_doc_published_tables_match_eval():
    _assert_scope_doc_published_tables_match_eval(_SCOPE_DOC)
    _assert_scope_doc_success_criteria_numbers(_SCOPE_DOC.read_text())
    _assert_scope_doc_published_n_inventory(_SCOPE_DOC.read_text())


def test_scope_doc_fence_inventory_catches_indented_executable_fence(
    tmp_path: Path,
):
    source = _SCOPE_DOC.read_text()
    old = "```\nimport json\nfrom pathlib import Path\nfrom scripts.eval_harness.audit_sampling import (\n    allocate,"
    new = "    ```\nimport json\nfrom pathlib import Path\nfrom scripts.eval_harness.audit_sampling import (\n    allocate,"
    assert old in source
    mutated = source.replace(old, new, 1)
    path = tmp_path / "descqual-2-fact-annotation-pilot.md"
    path.write_text(mutated)
    with pytest.raises(AssertionError, match="executable fence inventory"):
        _assert_scope_doc_fence_inventory(path.read_text())


def test_scope_doc_table_guard_rejects_blank_line_that_drops_rows(tmp_path: Path):
    source = _SCOPE_DOC.read_text()
    old = "| ±15 pp | 41 |\n| ±10 pp | 84 |"
    new = "| ±15 pp | 41 |\n\n| ±10 pp | 84 |"
    assert old in source
    mutated = source.replace(old, new, 1)
    path = tmp_path / "descqual-2-fact-annotation-pilot.md"
    path.write_text(mutated)
    with pytest.raises(AssertionError, match="all four published margin rows"):
        _assert_scope_doc_published_tables_match_eval(path)


def test_scope_doc_table_guard_rejects_duplicate_n_column(tmp_path: Path):
    source = _SCOPE_DOC.read_text()
    old = "| target margin | n |\n| --- | --- |\n| ±15 pp | 41 |"
    new = "| target margin | n | n |\n| --- | --- | --- |\n| ±15 pp | 41 | 41 |"
    assert old in source
    mutated = source.replace(old, new, 1)
    path = tmp_path / "descqual-2-fact-annotation-pilot.md"
    path.write_text(mutated)
    with pytest.raises(AssertionError, match="duplicate n"):
        _assert_scope_doc_published_tables_match_eval(path)


def test_scope_doc_success_criteria_guard_rejects_hidden_or_changed_n(tmp_path: Path):
    source = _SCOPE_DOC.read_text()
    old = "Full-sample n is the pre-registered planning value **n = 198** at ICC=0.20\n  (sensitivity **n = 239** at ICC=0.30)"
    new = "Full-sample n is the pre-registered planning value **n = 199** at ICC=0.20\n  (sensitivity **n = 240** at ICC=0.30)"
    assert old in source
    mutated = source.replace(old, new, 1)
    with pytest.raises(AssertionError, match="success criteria"):
        _assert_scope_doc_success_criteria_numbers(mutated)

    hidden = source.replace(
        "Full-sample n is the pre-registered planning value **n = 198** at ICC=0.20\n"
        "  (sensitivity **n = 239** at ICC=0.30), not a number derived from the 30-image draw.",
        "<!-- Full-sample n is the pre-registered planning value **n = 198** at ICC=0.20\n"
        "  (sensitivity **n = 239** at ICC=0.30), not a number derived from the 30-image draw. -->",
        1,
    )
    assert hidden != source
    path = tmp_path / "descqual-2-fact-annotation-pilot.md"
    path.write_text(hidden)
    with pytest.raises(AssertionError, match="success criteria"):
        _assert_scope_doc_success_criteria_numbers(path.read_text())


def test_scope_doc_quantity_inventory_rejects_prose_n_drift(tmp_path: Path):
    source = _SCOPE_DOC.read_text()
    old = "older pin `a=12.90` produced n=327"
    new = "older pin `a=12.90` produced n=328"
    assert old in source
    path = tmp_path / "descqual-2-fact-annotation-pilot.md"
    path.write_text(source.replace(old, new, 1))
    with pytest.raises(AssertionError, match="quantity inventory"):
        _assert_scope_doc_published_n_inventory(path.read_text())


@pytest.mark.parametrize(
    ("old", "new", "match"),
    [
        (
            "| **198** (planning) |",
            "| **199** (planning) |",
            r"table publishes 199.*eval returned 198",
        ),
        (
            "| 0.05 | 1.492 | 118 |",
            "| 0.05 | 1.493 | 118 |",
            r"table publishes 1.493.*eval returned 1.492",
        ),
        (
            "| 0.2 | 2.969 | **198** (planning) |",
            "| 0.21 | 2.969 | **198** (planning) |",
            r"table publishes 2.969.*eval returned 3.068",
        ),
        (
            "| ±10 pp | 84 |",
            "| ±10 pp | 85 |",
            r"table publishes 85.*eval returned 84",
        ),
    ],
)
def test_table_only_disagreement_is_caught(tmp_path: Path, old: str, new: str, match: str):
    source = _SCOPE_DOC.read_text()
    assert old in source
    mutated = source.replace(old, new, 1)
    assert mutated != source
    path = tmp_path / "descqual-2-fact-annotation-pilot.md"
    path.write_text(mutated)
    with pytest.raises(AssertionError, match=match):
        _assert_scope_doc_published_tables_match_eval(path)


def test_unrelated_markdown_table_is_not_audited(tmp_path: Path):
    extra = (
        "\n\n| annotator | gold accuracy |\n"
        "| --- | --- |\n"
        "| A | 999 |\n"
        "| B | 0 |\n"
    )
    path = tmp_path / "descqual-2-fact-annotation-pilot.md"
    path.write_text(_SCOPE_DOC.read_text() + extra)
    _assert_scope_doc_published_tables_match_eval(path)


def test_tilde_fence_published_disagreement_is_caught(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    lie = (
        _SCOPE_DOC.read_text().rstrip()
        + "\n\n~~~\n"
        "from scripts.eval_harness.audit_sampling import sample_size_for_margin\n"
        "sample_size_for_margin(margin=0.10, population=80)  # 99\n"
        "~~~\n"
    )
    path = tmp_path / "descqual-2-fact-annotation-pilot.md"
    path.write_text(lie)
    text = path.read_text()
    fences = _scope_doc_executable_fences(text)
    assert any(
        "sample_size_for_margin(margin=0.10, population=80)" in block for block in fences
    )
    with pytest.raises(AssertionError, match=r"publishes 99.*eval returned 44"):
        _assert_all_executable_fences_match_eval(text, monkeypatch)


def test_backtick_fence_body_containing_tildes_is_one_block():
    sample = (
        "intro\n"
        "```\n"
        "first  # 1\n"
        "~~~\n"
        "second  # 2\n"
        "```\n"
        "outro\n"
        "~~~\n"
        "third  # 3\n"
        "```\n"
        "fourth  # 4\n"
        "~~~\n"
    )
    blocks = _scope_doc_fence_blocks(sample)
    assert len(blocks) == 2
    assert "first  # 1" in blocks[0]
    assert "~~~" in blocks[0]
    assert "second  # 2" in blocks[0]
    assert "```" not in blocks[0]
    assert "third  # 3" in blocks[1]
    assert "```" in blocks[1]
    assert "fourth  # 4" in blocks[1]
    assert "first  # 1" not in blocks[1]


def test_allocate_sums_to_n():
    allocation = allocate(strata_sizes=FIR12_STRATA, n=84)
    assert sum(allocation.values()) == 84
    assert set(allocation) == set(FIR12_STRATA)
    assert all(0 <= allocation[name] <= size for name, size in FIR12_STRATA.items())


def test_precision_floor_raises_b_above_proportional():
    proportional = allocate(strata_sizes=FIR12_STRATA, n=84)
    floored = allocate(strata_sizes=FIR12_STRATA, n=84, precision_floors={"B_eyewear": 0.10})
    assert floored["B_eyewear"] == 44
    assert floored["B_eyewear"] > proportional["B_eyewear"]
    assert sum(floored.values()) == 84
    assert all(0 <= floored[name] <= size for name, size in FIR12_STRATA.items())
    record = floored.floors["B_eyewear"]
    assert record.n == 44
    assert record.deff_order is DeffOrder.FPC_ONLY
    assert record.deff == 1.0
    assert record.cluster_size is None
    assert record.icc is None


def test_allocate_refuses_when_precision_floors_exceed_n():
    # n=30 pilot: proportional B=4; B_eyewear ±10 pp floor needs 44 unclustered.
    proportional = allocate(strata_sizes=FIR12_STRATA, n=30)
    assert proportional["B_eyewear"] == 4
    with pytest.raises(
        AuditSamplingError, match=r"precision floors require n>=44, got n=30"
    ):
        allocate(
            strata_sizes=FIR12_STRATA,
            n=30,
            precision_floors={"B_eyewear": 0.10},
        )


def test_draw_is_deterministic_without_replacement_and_carries_pi():
    members = _members()
    allocation = allocate(strata_sizes=FIR12_STRATA, n=84, precision_floors={"B_eyewear": 0.10})
    first = draw(strata_members=members, allocation=allocation, seed=20260820)
    second = draw(strata_members=members, allocation=allocation, seed=20260820)
    other_seed = draw(strata_members=members, allocation=allocation, seed=7)

    assert first.units == second.units
    assert first.unit_ids != other_seed.unit_ids
    assert len(first.unit_ids) == len(set(first.unit_ids)) == 84
    counts: dict[str, int] = {}
    for unit in first.units:
        counts[unit.stratum] = counts.get(unit.stratum, 0) + 1
        n_h = allocation[unit.stratum]
        n_stratum = FIR12_STRATA[unit.stratum]
        assert 0 < unit.inclusion_probability <= 1
        assert unit.inclusion_probability == pytest.approx(n_h / n_stratum)
    assert counts == dict(allocation)
    assert counts == allocation.counts


def test_draw_does_not_take_the_first_n():
    members = _members()
    allocation = allocate(strata_sizes=FIR12_STRATA, n=84)
    sample = draw(strata_members=members, allocation=allocation, seed=20260820)
    convenience = []
    for stratum in sorted(members):
        convenience.extend(sorted(members[stratum])[: allocation[stratum]])
    assert list(sample.unit_ids) != convenience


def test_draw_is_invariant_to_member_order():
    members = _members()
    reversed_members = {name: list(reversed(ids)) for name, ids in members.items()}
    allocation = allocate(strata_sizes=FIR12_STRATA, n=84)
    a = draw(strata_members=members, allocation=allocation, seed=11)
    b = draw(strata_members=reversed_members, allocation=allocation, seed=11)
    assert set(a.unit_ids) == set(b.unit_ids)


def test_sample_size_rejects_non_positive_margin():
    with pytest.raises(AuditSamplingError):
        sample_size_for_margin(margin=0.0, population=640)


def test_clustered_b_eyewear_precision_floor_is_48():
    # AUDIT-11 / BR-33: a is the PSU partition of the 80-image B frame, not
    # the labeled-membership join (47 subjects, Σm=75, a=2.36) applied to 80.
    entries = json.loads(_FIR12_MANIFEST.read_text())["entries"]
    b_entries = [e for e in entries if e["stratum"] == "B_eyewear"]
    part = project_frame_psu_image_counts(b_entries)
    assert len(b_entries) == 80
    assert part.n_entries == 80
    assert part.n_psus == 55
    assert sum(part.sizes) == 80
    assert sum(m * m for m in part.sizes) == 168
    cluster_size = kish_effective_cluster_size(part.sizes)
    assert cluster_size == pytest.approx(168 / 80)
    assert cluster_size == pytest.approx(2.1)

    n0 = (1.96 * 1.96) * 0.5 * 0.5 / (0.10 * 0.10)
    icc = 0.2
    deff = 1.0 + (cluster_size - 1.0) * icc
    n_deff = n0 * deff
    n_raw = n_deff / (1.0 + (n_deff - 1.0) / 80)
    assert math.ceil(n_raw) == 48
    assert math.ceil(n0 / (1.0 + (n0 - 1.0) / 80)) == 44
    mean_n = size_for_margin(margin=0.10, population=80, cluster_size=80 / 47, icc=icc).n
    assert mean_n == 47

    spec = ClusterSpec(cluster_size=cluster_size, icc=icc)
    expected = size_for_margin(
        margin=0.10, population=80, cluster_size=cluster_size, icc=icc
    )
    assert expected.n == 48
    assert expected.deff_order is DeffOrder.DEFF_THEN_FPC
    assert expected.deff == pytest.approx(deff)
    assert expected.n_deff == pytest.approx(n_deff)

    unclustered = allocate(
        strata_sizes=FIR12_STRATA, n=84, precision_floors={"B_eyewear": 0.10}
    )
    clustered = allocate(
        strata_sizes=FIR12_STRATA,
        n=84,
        precision_floors={"B_eyewear": 0.10},
        cluster_params={"B_eyewear": spec},
    )
    assert isinstance(clustered, Allocation)
    assert unclustered["B_eyewear"] == 44
    assert clustered["B_eyewear"] == 48
    assert clustered["E_clean"] == 26
    assert clustered["B_eyewear"] != unclustered["B_eyewear"]
    assert sum(clustered.values()) == 84
    record = clustered.floors["B_eyewear"]
    assert record == expected
    assert record.n == 48
    assert record.deff_order is DeffOrder.DEFF_THEN_FPC
    assert record.deff_order == "deff_then_fpc"
    assert record.deff == pytest.approx(1.22)
    assert record.cluster_size == pytest.approx(cluster_size)
    assert record.icc == 0.2
    assert record.n / record.deff == pytest.approx(48 / deff)


def test_b_eyewear_labeled_subject_a_is_sized_against_its_own_frame():
    # Labeled-membership a=2.36 (177/75 over 47 overlapping subjects) is a
    # diagnostic of that join. AUDIT-11 forbids applying it to the 80-image
    # B frame; size it against population=75.
    entries = json.loads(_FIR12_MANIFEST.read_text())["entries"]
    b_entries = [e for e in entries if e["stratum"] == "B_eyewear"]
    labeled = project_strata_subject_image_counts(b_entries)["B_eyewear"]
    assert len(labeled) == 47
    assert sum(labeled) == 75
    assert sum(m * m for m in labeled) == 177
    labeled_a = kish_effective_cluster_size(labeled)
    assert labeled_a == pytest.approx(177 / 75)
    assert labeled_a == pytest.approx(2.36)
    own_frame = size_for_margin(
        margin=0.10, population=75, cluster_size=labeled_a, icc=0.2
    )
    assert own_frame.n == 47
    b_frame_a = kish_effective_cluster_size(
        project_frame_psu_image_counts(b_entries).sizes
    )
    planning = size_for_margin(
        margin=0.10, population=80, cluster_size=b_frame_a, icc=0.2
    )
    assert planning.n == 48
    assert own_frame.n != planning.n
    assert labeled_a != pytest.approx(b_frame_a)


def test_allocate_without_cluster_params_stays_deff_blind():
    allocation = allocate(
        strata_sizes=FIR12_STRATA, n=84, precision_floors={"B_eyewear": 0.10}
    )
    record = allocation.floors["B_eyewear"]
    assert allocation["B_eyewear"] == 44
    assert record.deff_order is DeffOrder.FPC_ONLY
    assert record.deff == 1.0
    assert record.cluster_size is None


def test_subject_image_counts_feed_kish_a():
    entries = [
        _entry("B_eyewear", ["alice"]),
        _entry("B_eyewear", ["alice"]),
        _entry("B_eyewear", ["alice"]),
        _entry("B_eyewear", ["alice"]),
        _entry("B_eyewear", ["bob"]),
        _entry("B_eyewear", ["cara"]),
        _entry("E_clean", ["dana"]),
        _entry("E_clean", ["dana"]),
        _entry("E_clean", []),
    ]
    sizes = project_strata_subject_image_counts(entries)
    assert sizes == {"B_eyewear": (4, 1, 1), "E_clean": (2,)}
    assert kish_effective_cluster_size(sizes["B_eyewear"]) == pytest.approx(3.0)
    assert kish_effective_cluster_size(sizes["E_clean"]) == pytest.approx(2.0)
    a = kish_effective_cluster_size(sizes["B_eyewear"])
    spec = ClusterSpec(cluster_size=a, icc=0.2)
    record = size_for_margin(
        margin=0.10, population=80, cluster_size=spec.cluster_size, icc=spec.icc
    )
    mean_record = size_for_margin(margin=0.10, population=80, cluster_size=2.0, icc=0.2)
    assert a == pytest.approx(3.0)
    assert spec.cluster_size != pytest.approx(2.0)
    assert record.n == 51
    assert mean_record.n == 48
    assert record.n != mean_record.n


def test_empty_present_identities_contribute_no_cluster():
    sizes = project_strata_subject_image_counts(
        [
            _entry("E_clean", ["Pat"]),
            _entry("E_clean", []),
            _entry("A_true_occluder", []),
        ]
    )
    assert sizes == {"E_clean": (1,)}
    assert "A_true_occluder" not in sizes


def test_subject_image_counts_reject_bare_string_identities():
    with pytest.raises(AuditSamplingError, match="sequence of names"):
        project_strata_subject_image_counts(
            [{"stratum": "E_clean", "present_identities": "Pat"}]
        )
    with pytest.raises(AuditSamplingError, match="sequence of objects"):
        project_strata_subject_image_counts("not-entries")  # type: ignore[arg-type]
    with pytest.raises(AuditSamplingError, match="missing 'stratum'"):
        project_strata_subject_image_counts([{"present_identities": ["Pat"]}])
    with pytest.raises(AuditSamplingError, match="non-empty str"):
        project_strata_subject_image_counts([_entry("E_clean", [""])])


def test_cluster_spec_rejects_out_of_bounds():
    with pytest.raises(AuditSamplingError, match="cluster_size"):
        ClusterSpec(cluster_size=0.5, icc=0.2)
    with pytest.raises(AuditSamplingError, match="cluster_size"):
        ClusterSpec(cluster_size=float("nan"), icc=0.2)
    with pytest.raises(AuditSamplingError, match="cluster_size"):
        ClusterSpec(cluster_size=float("inf"), icc=0.2)
    with pytest.raises(AuditSamplingError, match="icc"):
        ClusterSpec(cluster_size=2.0, icc=-0.1)
    with pytest.raises(AuditSamplingError, match="icc"):
        ClusterSpec(cluster_size=2.0, icc=2.0)
    with pytest.raises(AuditSamplingError, match="icc"):
        ClusterSpec(cluster_size=2.0, icc=float("nan"))


def test_design_effect_rejects_non_finite_as_audit_error():
    with pytest.raises(AuditSamplingError, match="cluster_size"):
        design_effect(cluster_size=float("nan"), icc=0.2)
    with pytest.raises(AuditSamplingError, match="cluster_size"):
        size_for_margin(margin=0.10, population=80, cluster_size=float("nan"), icc=0.2)
    with pytest.raises(AuditSamplingError, match="cluster_size"):
        size_for_margin(margin=0.10, population=80, cluster_size=float("inf"), icc=0.2)


def test_size_for_margin_rejects_overflow_derived_nan_as_audit_error():
    # Finite inputs that overflow n_deff to inf, then n = inf/inf = nan,
    # which math.ceil used to raise a raw ValueError (BR-10 only covered input nan).
    spec = ClusterSpec(cluster_size=1e308, icc=1.0)
    with pytest.raises(AuditSamplingError, match="non-finite"):
        size_for_margin(
            margin=0.10,
            population=640,
            cluster_size=spec.cluster_size,
            icc=spec.icc,
        )
    with pytest.raises(AuditSamplingError, match="non-finite"):
        size_for_margin(margin=0.10, population=640, cluster_size=1e308, icc=1.0)


def test_allocate_rejects_unknown_cluster_params_stratum():
    with pytest.raises(AuditSamplingError, match="cluster_params"):
        allocate(
            strata_sizes=FIR12_STRATA,
            n=84,
            precision_floors={"B_eyewear": 0.10},
            cluster_params={"not_a_stratum": ClusterSpec(cluster_size=2.0, icc=0.2)},
        )


def test_allocate_rejects_cluster_params_without_precision_floor():
    with pytest.raises(AuditSamplingError, match="no precision floor"):
        allocate(
            strata_sizes=FIR12_STRATA,
            n=84,
            cluster_params={"E_clean": ClusterSpec(cluster_size=2.0, icc=0.2)},
        )
    with pytest.raises(AuditSamplingError, match="no precision floor"):
        allocate(
            strata_sizes=FIR12_STRATA,
            n=84,
            precision_floors={"B_eyewear": 0.10},
            cluster_params={"E_clean": ClusterSpec(cluster_size=2.0, icc=0.2)},
        )


def test_allocation_source_dicts_cannot_mutate_constructed_object():
    counts = {"E_clean": 10, "B_eyewear": 4}
    floors = {}
    alloc = Allocation(counts=counts, floors=floors)
    counts["E_clean"] = 0
    floors["B_eyewear"] = size_for_margin(margin=0.10, population=80)
    assert alloc["E_clean"] == 10
    assert dict(alloc) == {"E_clean": 10, "B_eyewear": 4}
    assert "B_eyewear" not in alloc.floors


def test_allocation_hash_equal_for_equal_mappings():
    floor = size_for_margin(margin=0.10, population=80)
    a = Allocation(
        counts={"E_clean": 10, "B_eyewear": 4},
        floors={"B_eyewear": floor},
    )
    b = Allocation(
        counts={"B_eyewear": 4, "E_clean": 10},
        floors={"B_eyewear": floor},
    )
    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1
    different = Allocation(counts={"E_clean": 10, "B_eyewear": 4}, floors={})
    assert a != different
    assert hash(a) != hash(different)


def test_allocation_item_assignment_raises():
    alloc = Allocation(counts={"E_clean": 10}, floors={})
    with pytest.raises(TypeError):
        alloc["E_clean"] = 0
    with pytest.raises(TypeError):
        alloc.counts["E_clean"] = 0


def _anova_clusters_icc(*, n_psu: int, icc: float) -> list[tuple[float, ...]]:
    """Balanced k=3 clusters whose ANOVA ICC equals `icc` (MSW=1)."""
    k = 3
    f_ratio = (1.0 + (k - 1.0) * icc) / (1.0 - icc)
    target_ss = f_ratio * (n_psu - 1) / k
    center = (n_psu - 1) / 2.0
    raw = [i - center for i in range(n_psu)]
    scale = math.sqrt(target_ss / sum(x * x for x in raw))
    return [(scale * x - 1.0, scale * x, scale * x + 1.0) for x in raw]


def _gaussian_clusters(
    *, n_psu: int, n_within: int, rho: float, seed: int
) -> list[tuple[float, ...]]:
    rng = random.Random(seed)
    sd_a = math.sqrt(rho)
    sd_e = math.sqrt(1.0 - rho)
    clusters = []
    for _ in range(n_psu):
        intercept = rng.gauss(0.0, sd_a)
        clusters.append(
            tuple(intercept + rng.gauss(0.0, sd_e) for _ in range(n_within))
        )
    return clusters


def test_fir12_icc_eligible_subject_counts():
    assert sum(1 for m in WHOLE_FRAME.sizes if m >= 2) == 76
    assert sum(1 for m in WHOLE_FRAME.sizes if m >= 3) == 65


def test_draw_two_stage_replicates_within_psu():
    clusters = {f"s{i}": [f"s{i}-{j}" for j in range(4)] for i in range(12)}
    sample = draw_two_stage(clusters=clusters, n_psu=6, n_within=3, seed=21)
    by_psu: dict[object, int] = {}
    for unit in sample.units:
        assert unit.psu_id is not None
        by_psu[unit.psu_id] = by_psu.get(unit.psu_id, 0) + 1
        assert str(unit.unit_id).startswith(str(unit.psu_id))
    assert len(by_psu) == 6
    assert set(by_psu.values()) == {3}
    assert len(sample.units) == 18


def test_draw_two_stage_is_deterministic_and_order_invariant():
    clusters = {f"s{i}": [f"s{i}-{j}" for j in range(5)] for i in range(10)}
    reversed_clusters = {
        name: list(reversed(units)) for name, units in reversed(list(clusters.items()))
    }
    a = draw_two_stage(clusters=clusters, n_psu=4, n_within=2, seed=11)
    b = draw_two_stage(clusters=clusters, n_psu=4, n_within=2, seed=11)
    c = draw_two_stage(clusters=reversed_clusters, n_psu=4, n_within=2, seed=11)
    other = draw_two_stage(clusters=clusters, n_psu=4, n_within=2, seed=7)
    assert a.units == b.units
    assert {(u.psu_id, u.unit_id) for u in a.units} == {
        (u.psu_id, u.unit_id) for u in c.units
    }
    assert {(u.psu_id, u.unit_id) for u in a.units} != {
        (u.psu_id, u.unit_id) for u in other.units
    }


def test_draw_two_stage_carries_two_stage_inclusion_probability():
    clusters = {"alice": ["a1", "a2", "a3", "a4"], "bob": ["b1", "b2", "b3"]}
    sample = draw_two_stage(clusters=clusters, n_psu=2, n_within=2, seed=3)
    assert len(sample.units) == 4
    by_psu = {u.psu_id: u for u in sample.units}
    alice_pi = 1.0 * (2 / 4)
    bob_pi = 1.0 * (2 / 3)
    for unit in sample.units:
        expected = alice_pi if unit.psu_id == "alice" else bob_pi
        assert unit.inclusion_probability == pytest.approx(expected)
    assert set(by_psu) == {"alice", "bob"}


def test_draw_two_stage_refuses_n_within_below_2():
    clusters = {"s0": ["a", "b", "c"]}
    with pytest.raises(AuditSamplingError, match="n_within must be >= 2"):
        draw_two_stage(clusters=clusters, n_psu=1, n_within=1, seed=1)


def test_draw_two_stage_refuses_psu_smaller_than_n_within():
    clusters = {"s0": ["a", "b"], "s1": ["c", "d", "e"]}
    with pytest.raises(AuditSamplingError, match="n_within"):
        draw_two_stage(clusters=clusters, n_psu=2, n_within=3, seed=1)


def test_two_stage_census_of_m3_subjects_is_195_images():
    clusters = {
        f"s{i}": tuple(f"s{i}-{j}" for j in range(m))
        for i, m in enumerate(WHOLE_FRAME.sizes)
        if m >= 3
    }
    assert len(clusters) == 65
    sample = draw_two_stage(clusters=clusters, n_psu=65, n_within=3, seed=20260820)
    assert len(sample.units) == 195
    assert len({u.psu_id for u in sample.units}) == 65


def test_partition_census_of_m3_psus_is_192_images():
    n_m3 = sum(1 for m in FRAME_PSU.sizes if m >= 3)
    assert n_m3 == 64
    clusters = {
        f"s{i}": tuple(f"s{i}-{j}" for j in range(m))
        for i, m in enumerate(FRAME_PSU.sizes)
        if m >= 3
    }
    assert len(clusters) == 64
    sample = draw_two_stage(clusters=clusters, n_psu=64, n_within=3, seed=20260820)
    assert len(sample.units) == 192
    assert len({u.psu_id for u in sample.units}) == 64
    assert sum(1 for m in FRAME_PSU.sizes if m >= 2) == 76
    assert sum(1 for m in WHOLE_FRAME.sizes if m >= 3) == 65
    assert n_m3 != 65
    assert len(sample.units) != 195


def test_estimate_icc_anova_known_fixture():
    clusters = [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)]
    est = estimate_icc(clusters)
    assert est.n_psu == 3
    assert est.n_within == pytest.approx(2.0)
    assert est.n_obs == 6
    assert est.msb == pytest.approx(8.0)
    assert est.msw == pytest.approx(0.5)
    assert est.icc == pytest.approx(15 / 17)


def test_estimate_icc_fisher_z_ci_for_labeled_g65_k3_at_rho_02():
    # Labeled-a diagnostic, not planning n: k=65 is overlapping m≥3
    # (WHOLE_FRAME, Σm=544), so 121/284. Published CI n is 114/261 on
    # FRAME_PSU_KISH_A at k=64, icc=0.044/0.361 (AUDIT-11).
    clusters = _anova_clusters_icc(n_psu=65, icc=0.2)
    est = estimate_icc(clusters)
    assert est.icc == pytest.approx(0.2)
    assert est.n_psu == 65
    assert est.n_within == pytest.approx(3.0)
    assert est.lower == pytest.approx(0.045, abs=5e-4)
    assert est.upper == pytest.approx(0.360, abs=5e-4)
    low_n = size_for_margin(
        margin=0.10, population=640, cluster_size=WHOLE_FRAME_KISH_A, icc=0.045
    ).n
    high_n = size_for_margin(
        margin=0.10, population=640, cluster_size=WHOLE_FRAME_KISH_A, icc=0.360
    ).n
    assert low_n == 121
    assert high_n == 284
    published_low = size_for_margin(
        margin=0.10, population=640, cluster_size=FRAME_PSU_KISH_A, icc=0.044
    ).n
    published_high = size_for_margin(
        margin=0.10, population=640, cluster_size=FRAME_PSU_KISH_A, icc=0.361
    ).n
    assert published_low == 114
    assert published_high == 261
    assert (low_n, high_n) != (published_low, published_high)


def test_estimate_icc_recovers_rho_on_synthetic_clusters():
    clusters = _gaussian_clusters(n_psu=65, n_within=3, rho=0.2, seed=20260820)
    est = estimate_icc(clusters)
    assert est.lower < 0.2 < est.upper
    assert est.lower == pytest.approx(0.045, abs=0.15)
    assert est.upper == pytest.approx(0.360, abs=0.15)


def test_estimate_icc_rejects_singletons_and_too_few_psus():
    with pytest.raises(AuditSamplingError, match="at least 2"):
        estimate_icc([(1.0, 2.0, 3.0), (4.0,)])
    with pytest.raises(AuditSamplingError, match="n_psu"):
        estimate_icc([(1.0, 2.0), (3.0, 4.0)])
    with pytest.raises(AuditSamplingError, match="non-empty"):
        estimate_icc([])
