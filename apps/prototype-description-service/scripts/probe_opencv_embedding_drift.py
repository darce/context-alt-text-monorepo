#!/usr/bin/env python3
"""Measure whether an OpenCV version bump moves SFace embeddings far enough to
change an identity decision (CVUP1-LC-06).

The ``opencv-python`` pin in ``pyproject.toml`` carries a measured safety claim:
cross-version self-similarity sits far above the impostor band, and nearest-
neighbour flips on a consented corpus are classified against production decision
boundaries (auto-accept ceiling, suggestion band, reject). This script is the
instrument behind that claim. Without it the numbers can only be re-quoted from
a comment, and the next pin bump merges on the strength of a measurement nobody
can reproduce.

**Scope (aligner-path, OpenCV reference).** This probe runs
``OpenCVYuNetDetector`` + ``FivePointAligner`` + ``OpenCVSFaceEmbedder`` — the
same OpenCV reference path the golden generator uses. Production traffic goes
through ``FacePipelineFaceDetector`` (``OrtYuNetDetector`` + ``OrtSFaceEmbedder``),
sharing only ``FivePointAligner`` (``warpAffine``) with this path. ORT↔OpenCV
embedding/detection equivalence is carried by the ORT-vs-OpenCV parity suite
(``recognition/tests/unit/test_face_pipeline_ort_parity.py``, measured
``1-cos ≤ 5e-12``). This probe is therefore an aligner-scoped gate over the
OpenCV reference path, not a second production-path probe.

Two passes, one per OpenCV version:

    # OLD opencv, throwaway env (see the report artifact for the exact recipe):
    python scripts/probe_opencv_embedding_drift.py baseline \\
        --corpus "$GOLDEN_IMAGES_DIR" --out /tmp/acx-probe/cv4.npz

    # NEW opencv, project env:
    uv run python scripts/probe_opencv_embedding_drift.py compare \\
        --corpus "$GOLDEN_IMAGES_DIR" --baseline /tmp/acx-probe/cv4.npz \\
        --report docs/tasks/fir/evidence/opencv-5-embedding-drift.md

The ``.npz`` holds embeddings derived from consented corpus imagery — biometric
templates. Write it outside the repo and do not commit it. The report carries
aggregate statistics, version stamps and a corpus manifest digest only.

Faces are matched across versions by bbox IoU, never by detector output order: the
detector runs under both versions too, so its ordering is not a fixed point. Faces
with no counterpart above ``--match-iou`` are reported as unmatched rather than
dropped — a version bump that changes *which* faces are found is itself the finding.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

import cv2  # noqa: E402

# Import the submodules directly: the package __init__ pulls in the ORT adapters,
# and the old-version baseline pass runs in a minimal env with no onnxruntime.
from recognition.infrastructure.face_pipeline.aligner import FivePointAligner  # noqa: E402
from recognition.infrastructure.face_pipeline.opencv_ref import (  # noqa: E402
    OpenCVSFaceEmbedder,
    OpenCVYuNetDetector,
)

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# Decision-boundary fallbacks matching ClusteringSettings defaults. Duplicated
# rather than always imported: the baseline pass runs in a bare cv2+numpy env
# that may lack pydantic. `_decision_boundaries()` prefers live settings when
# available so a retune cannot silently leave the probe behind.
# `test_probe_match_threshold_tracks_settings` pins DEFAULT_MATCH_THRESHOLD to
# settings._LEGACY_SIMILARITY_THRESHOLD (the auto-accept / suggestion ceiling).
DEFAULT_MATCH_THRESHOLD = 0.55  # ClusteringSettings.suggestion_ceiling
DEFAULT_SUGGESTION_FLOOR = 0.35  # ClusteringSettings.suggestion_floor
DEFAULT_LOW_CONFIDENCE_BAND_WIDTH = 0.05  # ClusteringSettings.low_confidence_band_width


def _decision_boundaries() -> tuple[float, float, float, str]:
    """Return (effective_low_confidence_floor, suggestion_floor, suggestion_ceiling, source).

    Live ``ClusteringSettings`` when importable (source ``"settings"``); otherwise
    the three fallbacks above (source ``"fallback"``, effective floor =
    suggestion_floor - band_width = 0.30). The fallback must reproduce all three
    production boundaries — never collapse to a single threshold.
    """
    try:
        from recognition.application.settings.clustering import ClusteringSettings

        s = ClusteringSettings()
        return (
            s.effective_low_confidence_suggestion_floor,
            s.suggestion_floor,
            s.suggestion_ceiling,
            "settings",
        )
    except ImportError as exc:
        floor = DEFAULT_SUGGESTION_FLOOR
        width = DEFAULT_LOW_CONFIDENCE_BAND_WIDTH
        ceiling = DEFAULT_MATCH_THRESHOLD
        print(
            f"probe: ClusteringSettings unavailable ({exc}); "
            f"using fallback boundaries floor={floor} width={width} ceiling={ceiling}",
            file=sys.stderr,
        )
        return max(0.0, floor - width), floor, ceiling, "fallback"


@dataclass(frozen=True)
class Pass:
    """One version's run over the corpus."""

    keys: list[str]  # "<relpath>#<detector-order-index>"
    boxes: np.ndarray  # (N, 4) xywh
    embeddings: np.ndarray  # (N, 128) L2-normalised
    images: list[str]  # source relpath per row
    opencv_version: str
    numpy_version: str
    corpus_digest: str


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _corpus_files(corpus: Path) -> list[Path]:
    files = sorted(p for p in corpus.rglob("*") if p.is_file() and p.suffix.lower() in _IMAGE_SUFFIXES)
    if not files:
        raise SystemExit(f"probe: no images under {corpus}")
    return files


def _corpus_digest(corpus: Path, files: list[Path]) -> str:
    """Digest of (relpath, content-sha) pairs — identifies the corpus without naming it."""
    h = hashlib.sha256()
    for path in files:
        h.update(str(path.relative_to(corpus)).encode("utf-8"))
        h.update(_sha256_file(path).encode("ascii"))
    return h.hexdigest()


def run_pass(corpus: Path, *, score_threshold: float) -> Pass:
    files = _corpus_files(corpus)
    detector = OpenCVYuNetDetector(score_threshold=score_threshold)
    aligner = FivePointAligner()
    embedder = OpenCVSFaceEmbedder()

    keys: list[str] = []
    images: list[str] = []
    boxes: list[np.ndarray] = []
    crops: list[np.ndarray] = []
    for path in files:
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            print(f"probe: unreadable, skipping: {path}", file=sys.stderr)
            continue
        rel = str(path.relative_to(corpus))
        for idx, face in enumerate(detector.detect([img])[0]):
            keys.append(f"{rel}#{idx}")
            images.append(rel)
            boxes.append(np.asarray(face.bbox, dtype=np.float64))
            crops.append(aligner.align(img, face.landmarks).crop)

    if not crops:
        raise SystemExit(f"probe: detected zero faces across {len(files)} images")
    vectors = embedder.embed(crops).vectors.astype(np.float64)
    return Pass(
        keys=keys,
        boxes=np.stack(boxes),
        embeddings=vectors,
        images=images,
        opencv_version=cv2.__version__,
        numpy_version=np.__version__,
        corpus_digest=_corpus_digest(corpus, files),
    )


def save_pass(result: Pass, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        out,
        keys=np.asarray(result.keys),
        boxes=result.boxes,
        embeddings=result.embeddings,
        images=np.asarray(result.images),
        meta=np.asarray(
            json.dumps(
                {
                    "opencv_version": result.opencv_version,
                    "numpy_version": result.numpy_version,
                    "corpus_digest": result.corpus_digest,
                }
            )
        ),
    )


def load_pass(path: Path) -> Pass:
    data = np.load(path, allow_pickle=False)
    meta = json.loads(str(data["meta"]))
    return Pass(
        keys=[str(k) for k in data["keys"]],
        boxes=data["boxes"],
        embeddings=data["embeddings"],
        images=[str(i) for i in data["images"]],
        opencv_version=meta["opencv_version"],
        numpy_version=meta["numpy_version"],
        corpus_digest=meta["corpus_digest"],
    )


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix0, iy0 = max(ax, bx), max(ay, by)
    ix1, iy1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return float(inter / union) if union > 0 else 0.0


def match_faces(base: Pass, cur: Pass, *, min_iou: float) -> tuple[list[tuple[int, int]], list[str], list[str]]:
    """Greedy per-image IoU matching. Returns (pairs, unmatched_base, unmatched_cur)."""
    pairs: list[tuple[int, int]] = []
    taken_cur: set[int] = set()
    by_image_cur: dict[str, list[int]] = {}
    for j, img in enumerate(cur.images):
        by_image_cur.setdefault(img, []).append(j)

    for i, img in enumerate(base.images):
        candidates = [j for j in by_image_cur.get(img, []) if j not in taken_cur]
        if not candidates:
            continue
        best = max(candidates, key=lambda j: _iou(base.boxes[i], cur.boxes[j]))
        if _iou(base.boxes[i], cur.boxes[best]) >= min_iou:
            pairs.append((i, best))
            taken_cur.add(best)

    matched_base = {i for i, _ in pairs}
    unmatched_base = [base.keys[i] for i in range(len(base.keys)) if i not in matched_base]
    unmatched_cur = [cur.keys[j] for j in range(len(cur.keys)) if j not in taken_cur]
    return pairs, unmatched_base, unmatched_cur


def redact(key: str) -> str:
    """``<relpath>#<idx>`` -> ``<8-hex>#<idx>``.

    Corpus filenames name the consented people in them. The report is committed;
    the filenames must not be. The digest is stable, so a re-run still points at
    the same face — pass ``--reveal-keys`` to print the mapping locally.
    """
    rel, _, idx = key.rpartition("#")
    return f"{hashlib.sha256(rel.encode('utf-8')).hexdigest()[:8]}#{idx}"


def analyse(
    base: Pass,
    cur: Pass,
    *,
    min_iou: float,
    suggestion_ceiling: float,
    suggestion_floor: float,
    suggestion_band_floor: float,
) -> dict:
    pairs, unmatched_base, unmatched_cur = match_faces(base, cur, min_iou=min_iou)
    # Empty pairs → float64 np.asarray([]) and embeddings[bi] IndexError; return
    # the normal stats shape so verdict can surface a corpus-mismatch FAIL.
    if not pairs:
        return {
            "faces_matched": 0,
            "faces_baseline": len(base.keys),
            "faces_current": len(cur.keys),
            "unmatched_baseline": [redact(k) for k in unmatched_base],
            "unmatched_current": [redact(k) for k in unmatched_cur],
            "match_iou_floor": min_iou,
            "self_similarity": {"min": 0.0, "p05": 0.0, "median": 0.0},
            "impostor": {
                "pairs": 0,
                "p95": None,
                "max": None,
                "definition": "cross-image pairs within the baseline pass; repeat subjects inflate the tail",
            },
            "match_threshold": suggestion_ceiling,
            "suggestion_ceiling": suggestion_ceiling,
            "suggestion_floor": suggestion_floor,
            "suggestion_band_floor": suggestion_band_floor,
            "decisive_nn_flips": [],
            "suggestion_band_nn_flips": [],
            "subthreshold_nn_flips": [],
            "baseline": {
                "opencv_version": base.opencv_version,
                "numpy_version": base.numpy_version,
                "corpus_digest": base.corpus_digest,
            },
            "current": {
                "opencv_version": cur.opencv_version,
                "numpy_version": cur.numpy_version,
                "corpus_digest": cur.corpus_digest,
            },
            "corpus_digest_match": base.corpus_digest == cur.corpus_digest,
            "ok": False,
            "why": (
                "zero faces matched across versions — corpus mismatch or detector "
                "change moved every box below the IoU floor"
            ),
        }

    bi = np.asarray([i for i, _ in pairs], dtype=int)
    ci = np.asarray([j for _, j in pairs], dtype=int)
    be, ce = base.embeddings[bi], cur.embeddings[ci]
    images = [base.images[i] for i in bi]
    keys = [base.keys[i] for i in bi]

    self_sim = np.sum(be * ce, axis=1)

    sim_base, sim_cur = be @ be.T, ce @ ce.T

    # Impostor band: cross-IMAGE pairs within the baseline pass. Repeat subjects
    # across images land in this set, so the high tail is contaminated upward —
    # the reported separation is a floor, not a best case. Say so in the report
    # rather than quietly filtering, which would need identity labels this corpus
    # does not carry.
    same_image = np.asarray(images)[:, None] == np.asarray(images)[None, :]
    off_diag = ~np.eye(len(bi), dtype=bool)
    impostor = sim_base[off_diag & ~same_image]

    # Nearest-neighbour flips, split by production decision region:
    #   decisive        top ≥ suggestion_ceiling  → auto-accept (fail the gate)
    #   suggestion_band top ≥ effective low-conf floor → human-visible suggestion
    #   subthreshold    below that → matcher rejects either neighbour
    # A flip at cosine ~0.37 sits in the suggestion band: it reorders which face
    # a reviewer is shown as the top suggestion. That is not "no decision
    # affected"; report it as a suggestion-band event, not a sub-threshold
    # non-match.
    np.fill_diagonal(sim_base, -np.inf)
    np.fill_diagonal(sim_cur, -np.inf)
    nn_base = np.argmax(sim_base, axis=1)
    nn_cur = np.argmax(sim_cur, axis=1)

    decisive: list[dict] = []
    suggestion_band: list[dict] = []
    subthreshold: list[dict] = []
    for i in np.where(nn_base != nn_cur)[0]:
        b_nn, c_nn = int(nn_base[i]), int(nn_cur[i])
        detail = {
            "face": redact(keys[i]),
            "baseline_nn": redact(keys[b_nn]),
            "baseline_nn_cosine": float(sim_base[i, b_nn]),
            "current_nn": redact(keys[c_nn]),
            "current_nn_cosine": float(sim_cur[i, c_nn]),
        }
        top = max(detail["baseline_nn_cosine"], detail["current_nn_cosine"])
        if top >= suggestion_ceiling:
            decisive.append(detail)
        elif top >= suggestion_band_floor:
            suggestion_band.append(detail)
        else:
            subthreshold.append(detail)

    return {
        "faces_matched": int(len(bi)),
        "faces_baseline": len(base.keys),
        "faces_current": len(cur.keys),
        "unmatched_baseline": [redact(k) for k in unmatched_base],
        "unmatched_current": [redact(k) for k in unmatched_cur],
        "match_iou_floor": min_iou,
        "self_similarity": {
            "min": float(np.min(self_sim)),
            "p05": float(np.percentile(self_sim, 5)),
            "median": float(np.median(self_sim)),
        },
        "impostor": {
            "pairs": int(impostor.size),
            "p95": float(np.percentile(impostor, 95)) if impostor.size else None,
            "max": float(np.max(impostor)) if impostor.size else None,
            "definition": "cross-image pairs within the baseline pass; repeat subjects inflate the tail",
        },
        # match_threshold retained as the auto-accept ceiling for older report readers.
        "match_threshold": suggestion_ceiling,
        "suggestion_ceiling": suggestion_ceiling,
        "suggestion_floor": suggestion_floor,
        "suggestion_band_floor": suggestion_band_floor,
        "decisive_nn_flips": decisive,
        "suggestion_band_nn_flips": suggestion_band,
        "subthreshold_nn_flips": subthreshold,
        "baseline": {
            "opencv_version": base.opencv_version,
            "numpy_version": base.numpy_version,
            "corpus_digest": base.corpus_digest,
        },
        "current": {
            "opencv_version": cur.opencv_version,
            "numpy_version": cur.numpy_version,
            "corpus_digest": cur.corpus_digest,
        },
        "corpus_digest_match": base.corpus_digest == cur.corpus_digest,
    }


def verdict(stats: dict) -> tuple[bool, str]:
    """Decision-safety verdict against production match / suggestion boundaries."""
    if stats.get("ok") is False and stats.get("why"):
        return False, str(stats["why"])
    reasons: list[str] = []
    if not stats["corpus_digest_match"]:
        reasons.append("baseline and current ran over different corpora")
    if stats["unmatched_baseline"] or stats["unmatched_current"]:
        reasons.append(
            f"{len(stats['unmatched_baseline'])} baseline / {len(stats['unmatched_current'])} "
            "current faces had no cross-version counterpart"
        )
    if stats["decisive_nn_flips"]:
        reasons.append(
            f"{len(stats['decisive_nn_flips'])} nearest-neighbour flip(s) at or above the "
            f"{stats['suggestion_ceiling']} auto-accept ceiling"
        )
    p95 = stats["impostor"]["p95"]
    lo = stats["self_similarity"]["min"]
    if p95 is not None and lo <= p95:
        reasons.append(f"worst self-similarity {lo:.6f} is not above impostor p95 {p95:.6f}")
    if reasons:
        return False, "; ".join(reasons)

    # Suggestion-band flips are user-visible (reordered top suggestions) but not
    # auto-accepts. Fail only on decisive flips; surface suggestion-band events
    # as a non-fatal warning so the gate cannot read as "no decision affected".
    parts = ["self-similarity clears the impostor band"]
    sug = len(stats["suggestion_band_nn_flips"])
    if sug:
        band_lo = stats["suggestion_band_floor"]
        ceiling = stats["suggestion_ceiling"]
        parts.append(
            f"{sug} suggestion-band flip(s) in [{band_lo}, {ceiling}) — "
            "reordered human-visible suggestions, not auto-accepts (non-fatal)"
        )
    sub = len(stats["subthreshold_nn_flips"])
    if sub:
        parts.append(
            f"{sub} sub-threshold flip(s) below {stats['suggestion_band_floor']} (matcher rejects either neighbour)"
        )
    return True, "; ".join(parts)


def render_report(
    stats: dict,
    ok: bool,
    why: str,
    *,
    boundary_source: str,
    match_threshold_overridden: bool,
    argv: list[str],
) -> str:
    ss, im = stats["self_similarity"], stats["impostor"]
    ceiling = stats["suggestion_ceiling"]
    band_lo = stats["suggestion_band_floor"]
    if match_threshold_overridden:
        boundary_line = (
            f"Decision boundaries: source={boundary_source}, suggestion_ceiling overridden "
            f"via --match-threshold to {ceiling}"
        )
    elif boundary_source == "settings":
        boundary_line = "Decision boundaries match production ClusteringSettings"
    else:
        boundary_line = (
            f"Decision boundaries from hardcoded fallbacks (ClusteringSettings unavailable; source={boundary_source})"
        )
    impostor_p95 = "n/a" if im["p95"] is None else f"{im['p95']:.4f}"
    impostor_max = "n/a" if im["max"] is None else f"{im['max']:.4f}"
    return "\n".join(
        [
            "# OpenCV version bump — embedding drift probe",
            "",
            f"Generated by `scripts/probe_opencv_embedding_drift.py compare`. Verdict: **{'PASS' if ok else 'FAIL'}** — {why}.",
            "",
            f"Invocation: `{' '.join(argv)}`",
            "",
            "| | |",
            "| --- | --- |",
            f"| baseline OpenCV | {stats['baseline']['opencv_version']} (numpy {stats['baseline']['numpy_version']}) |",
            f"| current OpenCV | {stats['current']['opencv_version']} (numpy {stats['current']['numpy_version']}) |",
            f"| corpus digest | `{stats['current']['corpus_digest'][:16]}…` (match: {stats['corpus_digest_match']}) |",
            f"| faces matched | {stats['faces_matched']} of {stats['faces_baseline']} baseline / {stats['faces_current']} current |",
            f"| unmatched | {len(stats['unmatched_baseline'])} baseline, {len(stats['unmatched_current'])} current (IoU floor {stats['match_iou_floor']}) |",
            f"| cross-version self-similarity | min {ss['min']:.9f}, p05 {ss['p05']:.9f}, median {ss['median']:.9f} |",
            f"| impostor cosine | p95 {impostor_p95}, max {impostor_max} over {im['pairs']} pairs |",
            f"| NN flips at or above auto-accept ceiling {ceiling} | {len(stats['decisive_nn_flips'])} |",
            f"| NN flips in suggestion band [{band_lo}, {ceiling}) | {len(stats['suggestion_band_nn_flips'])} |",
            f"| NN flips below suggestion band ({band_lo}) | {len(stats['subthreshold_nn_flips'])} |",
            f"| boundary source | {boundary_source}"
            + (" (suggestion_ceiling CLI override)" if match_threshold_overridden else "")
            + " |",
            "",
            f"Impostor band definition: {im['definition']}.",
            "",
            f"{boundary_line}: auto-accept at/above",
            f"suggestion_ceiling ({ceiling}), human-visible suggestions in",
            f"[{band_lo}, {ceiling}), reject below {band_lo}. Decisive flips fail the",
            "gate. Suggestion-band flips reorder which neighbour a reviewer sees and are",
            'reported as a non-fatal warning — not as "no decision affected".',
            "",
            "Measurement scope: OpenCV reference path (YuNet + SFace via cv2) sharing",
            "FivePointAligner with production; ORT-path equivalence is the",
            "ORT-vs-OpenCV parity suite (`test_face_pipeline_ort_parity.py`).",
            "",
            "Re-run before changing the `opencv-python` pin. The raw embeddings are biometric",
            "templates derived from consented imagery and are deliberately not committed;",
            "only the aggregates above leave the operator's machine.",
            "",
            "```json",
            json.dumps(stats, indent=2, sort_keys=True),
            "```",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--corpus", type=Path, required=True, help="directory of consented corpus images")
    common.add_argument("--score-threshold", type=float, default=0.9)

    p_base = sub.add_parser("baseline", parents=[common], help="record embeddings under the current OpenCV")
    p_base.add_argument("--out", type=Path, required=True, help="npz path OUTSIDE the repo (biometric templates)")

    p_cmp = sub.add_parser("compare", parents=[common], help="re-run and compare against a baseline npz")
    p_cmp.add_argument("--baseline", type=Path, required=True)
    p_cmp.add_argument("--report", type=Path, help="write a markdown report here")
    p_cmp.add_argument("--match-iou", type=float, default=0.5, help="bbox IoU floor for cross-version face matching")
    p_cmp.add_argument(
        "--match-threshold",
        type=float,
        default=None,
        help="override suggestion_ceiling (auto-accept); default from ClusteringSettings",
    )
    p_cmp.add_argument(
        "--reveal-keys",
        action="store_true",
        help="print the redacted-digest -> corpus-filename mapping to stderr (local debugging only)",
    )

    args = parser.parse_args(argv)

    if args.mode == "baseline":
        result = run_pass(args.corpus, score_threshold=args.score_threshold)
        save_pass(result, args.out)
        print(f"probe: {len(result.keys)} faces under OpenCV {result.opencv_version} -> {args.out}")
        return 0

    band_floor, sug_floor, ceiling, boundary_source = _decision_boundaries()
    match_threshold_overridden = args.match_threshold is not None
    if match_threshold_overridden:
        ceiling = args.match_threshold

    cur = run_pass(args.corpus, score_threshold=args.score_threshold)
    base = load_pass(args.baseline)
    stats = analyse(
        base,
        cur,
        min_iou=args.match_iou,
        suggestion_ceiling=ceiling,
        suggestion_floor=sug_floor,
        suggestion_band_floor=band_floor,
    )
    ok, why = verdict(stats)
    if args.reveal_keys:
        # Console only, never the report: maps redacted digests back to filenames.
        for key in cur.keys:
            print(f"reveal {redact(key)} = {key}", file=sys.stderr)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        report_argv = list(sys.argv if argv is None else [sys.argv[0], *argv])
        args.report.write_text(
            render_report(
                stats,
                ok,
                why,
                boundary_source=boundary_source,
                match_threshold_overridden=match_threshold_overridden,
                argv=report_argv,
            ),
            encoding="utf-8",
        )
        print(f"probe: report -> {args.report}")
    print(json.dumps(stats, indent=2, sort_keys=True))
    print(f"probe: {'PASS' if ok else 'FAIL'} — {why}")
    # Non-zero on a decision-affecting drift: this is a gate, not a printout.
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
