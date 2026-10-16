"""FIRBENCH-1 comparison explorer: one static, offline page from a comparison export file.

The page reads only the export (``firbench/comparison-explorer-export-v1``). It never opens a database, a
report, or a path named in the export. Every value on the page is copied from the export. A value the
export does not carry is shown as "not recorded", never as zero. The pipelines are historical results side
by side, not a ranking, and the page evaluates no hypothesis and no guardrail.
"""

from __future__ import annotations

import ctypes
import errno
import html
import json
import math
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from scripts.eval_harness.firbench_contract import FirBenchError

EXPORT_SCHEMA = "firbench/comparison-explorer-export-v1"
EXPORT_SCHEMA_VERSION = 1
MAX_EXPORT_BYTES = 1 << 20
MAX_ENTRIES = 64
MAX_COUNT = (1 << 31) - 1
PAGE_NAME = "index.html"
PIPELINE_ORDER = ("auraface", "sface", "insightface")
PIPELINE_LABELS = {"auraface": "AuraFace", "sface": "SFace", "insightface": "InsightFace"}
MODEL_PIPELINES = {"ort-yunet-sface": "sface", "buffalo_l": "insightface", "auraface": "auraface"}
SOURCE_KINDS = ("report-json", "scores-json", "run-manifest")
MANIFEST_HASH_KINDS = ("raw-sha256", "legacy-model-dump-sha256")
QUALIFICATIONS = ("unqualified", "partial")
SLICE_SECTIONS = (
    "clustering",
    "demographic",
    "full_corpus_identification",
    "headline_identification",
    "occlusion",
    "unknown_rejection",
)
ROOT_KEYS = frozenset({"schema", "schema_version", "sources", "dedup", "reports"})
SOURCE_KEYS = frozenset(
    {"artifact_id", "file_sha256", "kind", "manifest_hash_kind", "manifest_sha256", "qualification", "source_sha"}
)
DEDUP_KEYS = frozenset({"file_sha256", "artifact_ids"})
REPORT_KEYS = frozenset(
    {
        "artifact_id",
        "file_sha256",
        "pipeline",
        "model_id",
        "embedding_dim",
        "counts",
        "detection",
        "unknown_rejection",
        "clustering",
        "identification",
        "slice_sections",
        "compatibility",
        "qualification",
    }
)
COUNT_KEYS = frozenset({"total", "scored", "failed", "matched_faces", "named_matched", "stranger_matched"})
DETECTION_KEYS = frozenset({"tp", "fp", "fn", "precision", "recall"})
UNKNOWN_REJECTION_KEYS = frozenset(
    {"correct_rejects", "false_accepts", "n", "n_floor", "rate", "rate_numerator", "rate_denominator"}
)
CLUSTERING_KEYS = frozenset(
    {
        "false_merge",
        "false_split",
        "purity",
        "n_faces",
        "n_clusters",
        "m_co_clustered",
        "p_diff",
        "p_same",
        "algorithm",
        "metric",
        "parameters",
    }
)
IDENTIFICATION_KEYS = frozenset({"headline", "full"})
IDENTIFICATION_SECTION_KEYS = frozenset(
    {
        "tp",
        "fp",
        "fn",
        "precision",
        "recall",
        "precision_numerator",
        "precision_denominator",
        "recall_numerator",
        "recall_denominator",
        "n_named_probes",
        "n_recall_eligible",
        "missed_gt",
        "unmatched_detections",
        "wrong_names",
        "n_floor",
    }
)
_IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHA1 = re.compile(r"^[0-9a-f]{40}$")


class ExplorerError(FirBenchError):
    """A refused export or output. The message is fixed text plus a schema location, never a raw value."""


def _refuse(where: str, problem: str) -> ExplorerError:
    return ExplorerError(f"invalid explorer export: {problem} at {where}")


def _refuse_constant(_name: str) -> None:
    raise ExplorerError("invalid explorer export: non-finite number")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ExplorerError("invalid explorer export: duplicate key")
        result[key] = value
    return result


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _mapping(value: object, where: str, keys: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _refuse(where, "expected an object")
    if set(value) - keys:
        raise _refuse(where, "unknown field")
    if keys - set(value):
        raise _refuse(where, "missing field")
    return value


def _entries(value: object, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise _refuse(where, "expected a list")
    if len(value) > MAX_ENTRIES:
        raise _refuse(where, "too many entries")
    return value


def _ident(value: object, where: str) -> str:
    if not isinstance(value, str) or _IDENT.fullmatch(value) is None:
        raise _refuse(where, "not a safe identifier")
    return value


def _digest(value: object, where: str, pattern: re.Pattern[str], *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise _refuse(where, "not a lowercase hex digest")
    return value


def _choice(value: object, where: str, options: tuple[str, ...], *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or value not in options:
        raise _refuse(where, "unknown value")
    return value


def _count(value: object, where: str) -> int | None:
    if value is None:
        return None
    if not _is_int(value) or not 0 <= value <= MAX_COUNT:
        raise _refuse(where, "expected a non-negative integer or null")
    return value


def _number(value: object, where: str, low: float, high: float) -> float | None:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or (isinstance(value, float) and not math.isfinite(value))
    ):
        raise _refuse(where, "expected a finite number or null")
    if not low <= value <= high:
        raise _refuse(where, "number out of range")
    return float(value)


def _counts(value: object, where: str) -> dict[str, int | None]:
    section = _mapping(value, where, COUNT_KEYS)
    return {key: _count(section[key], f"{where}.{key}") for key in sorted(COUNT_KEYS)}


def _detection(value: object, where: str) -> dict[str, int | float | None]:
    section = _mapping(value, where, DETECTION_KEYS)
    return {
        "tp": _count(section["tp"], f"{where}.tp"),
        "fp": _count(section["fp"], f"{where}.fp"),
        "fn": _count(section["fn"], f"{where}.fn"),
        "precision": _number(section["precision"], f"{where}.precision", 0.0, 1.0),
        "recall": _number(section["recall"], f"{where}.recall", 0.0, 1.0),
    }


def _unknown_rejection(value: object, where: str) -> dict[str, Any] | None:
    if value is None:
        return None
    section = _mapping(value, where, UNKNOWN_REJECTION_KEYS)
    return {
        "correct_rejects": _count(section["correct_rejects"], f"{where}.correct_rejects"),
        "false_accepts": _count(section["false_accepts"], f"{where}.false_accepts"),
        "n": _count(section["n"], f"{where}.n"),
        "n_floor": _count(section["n_floor"], f"{where}.n_floor"),
        "rate": _number(section["rate"], f"{where}.rate", 0.0, 1.0),
        "rate_numerator": _count(section["rate_numerator"], f"{where}.rate_numerator"),
        "rate_denominator": _count(section["rate_denominator"], f"{where}.rate_denominator"),
    }


def _clustering(value: object, where: str) -> dict[str, Any] | None:
    if value is None:
        return None
    section = _mapping(value, where, CLUSTERING_KEYS)
    parameters = section["parameters"]
    d_cut = None
    if parameters is not None:
        parameters = _mapping(parameters, f"{where}.parameters", frozenset({"d_cut"}))
        d_cut = _number(parameters["d_cut"], f"{where}.parameters.d_cut", 0.0, 2.0)
    return {
        "d_cut": d_cut,
        "false_merge": _number(section["false_merge"], f"{where}.false_merge", 0.0, 1.0),
        "false_split": _number(section["false_split"], f"{where}.false_split", 0.0, 1.0),
        "purity": _number(section["purity"], f"{where}.purity", 0.0, 1.0),
        "n_faces": _count(section["n_faces"], f"{where}.n_faces"),
        "n_clusters": _count(section["n_clusters"], f"{where}.n_clusters"),
        "m_co_clustered": _count(section["m_co_clustered"], f"{where}.m_co_clustered"),
        "p_diff": _count(section["p_diff"], f"{where}.p_diff"),
        "p_same": _count(section["p_same"], f"{where}.p_same"),
        "algorithm": _choice(
            section["algorithm"], f"{where}.algorithm", ("hdbscan", "average", "complete", "median"), nullable=True
        ),
        "metric": _choice(section["metric"], f"{where}.metric", ("cosine", "euclidean"), nullable=True),
    }


def _identification(value: object, where: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise _refuse(where, "expected an object")
    if set(value) - IDENTIFICATION_KEYS:
        raise _refuse(where, "unknown field")
    section = value
    result: dict[str, Any] = {}
    for name in sorted(section):
        block = section[name]
        if block is None:
            result[name] = None
            continue
        if not isinstance(block, dict) or set(block) - IDENTIFICATION_SECTION_KEYS:
            raise _refuse(f"{where}.{name}", "unknown field")
        result[name] = {
            key: (
                _number(item, f"{where}.{name}.{key}", 0.0, 1.0)
                if key in ("precision", "recall")
                else _count(item, f"{where}.{name}.{key}")
            )
            for key, item in sorted(block.items())
        }
    return result


def _validate(root: object) -> dict[str, Any]:
    root = _mapping(root, "root", ROOT_KEYS)
    if root["schema"] != EXPORT_SCHEMA:
        raise ExplorerError("invalid explorer export: unsupported export schema")
    version = root["schema_version"]
    if not _is_int(version) or version != EXPORT_SCHEMA_VERSION:
        raise ExplorerError(
            "invalid explorer export: unsupported export schema_version (this explorer reads version 1)"
        )
    sources = []
    for index, item in enumerate(_entries(root["sources"], "sources")):
        where = f"sources[{index}]"
        source = _mapping(item, where, SOURCE_KEYS)
        sources.append(
            {
                "artifact_id": _ident(source["artifact_id"], f"{where}.artifact_id"),
                "file_sha256": _digest(source["file_sha256"], f"{where}.file_sha256", _SHA256),
                "kind": _choice(source["kind"], f"{where}.kind", SOURCE_KINDS),
                "manifest_hash_kind": _choice(
                    source["manifest_hash_kind"], f"{where}.manifest_hash_kind", MANIFEST_HASH_KINDS, nullable=True
                ),
                "manifest_sha256": _digest(
                    source["manifest_sha256"], f"{where}.manifest_sha256", _SHA256, nullable=True
                ),
                "qualification": _choice(source["qualification"], f"{where}.qualification", QUALIFICATIONS),
                "source_sha": _digest(source["source_sha"], f"{where}.source_sha", _SHA1, nullable=True),
            }
        )
    dedup = []
    for index, item in enumerate(_entries(root["dedup"], "dedup")):
        where = f"dedup[{index}]"
        group = _mapping(item, where, DEDUP_KEYS)
        dedup.append(
            {
                "file_sha256": _digest(group["file_sha256"], f"{where}.file_sha256", _SHA256),
                "artifact_ids": sorted(
                    _ident(name, f"{where}.artifact_ids") for name in _entries(group["artifact_ids"], where)
                ),
            }
        )
    reports = []
    for index, item in enumerate(_entries(root["reports"], "reports")):
        where = f"reports[{index}]"
        report = _mapping(item, where, REPORT_KEYS)
        pipeline = _choice(report["pipeline"], f"{where}.pipeline", PIPELINE_ORDER, nullable=True)
        model_id = report["model_id"]
        if model_id is not None and (not isinstance(model_id, str) or model_id not in MODEL_PIPELINES):
            raise _refuse(f"{where}.model_id", "unknown model")
        if model_id is not None and pipeline != MODEL_PIPELINES[model_id]:
            raise _refuse(where, "pipeline does not match model")
        embedding_dim = report["embedding_dim"]
        if embedding_dim is not None and not (_is_int(embedding_dim) and 1 <= embedding_dim <= 4096):
            raise _refuse(f"{where}.embedding_dim", "expected a dimension or null")
        if report["compatibility"] != "unknown":
            raise _refuse(f"{where}.compatibility", "unsupported value")
        slices = _entries(report["slice_sections"], f"{where}.slice_sections")
        reports.append(
            {
                "artifact_id": _ident(report["artifact_id"], f"{where}.artifact_id"),
                "file_sha256": _digest(report["file_sha256"], f"{where}.file_sha256", _SHA256),
                "pipeline": pipeline,
                "model_id": model_id,
                "embedding_dim": embedding_dim,
                "counts": _counts(report["counts"], f"{where}.counts"),
                "detection": _detection(report["detection"], f"{where}.detection"),
                "unknown_rejection": _unknown_rejection(report["unknown_rejection"], f"{where}.unknown_rejection"),
                "clustering": _clustering(report["clustering"], f"{where}.clustering"),
                "identification": _identification(report["identification"], f"{where}.identification"),
                "slice_sections": sorted(_choice(name, f"{where}.slice_sections", SLICE_SECTIONS) for name in slices),
                "qualification": _choice(report["qualification"], f"{where}.qualification", QUALIFICATIONS),
            }
        )
    return _cross_check(sources, dedup, reports)


def _cross_check(
    sources: list[dict[str, Any]], dedup: list[dict[str, Any]], reports: list[dict[str, Any]]
) -> dict[str, Any]:
    ids = [source["artifact_id"] for source in sources]
    if len(set(ids)) != len(ids):
        raise ExplorerError("invalid explorer export: duplicate artifact_id in sources")
    aliases: dict[str, list[str]] = {}
    for source in sources:
        aliases.setdefault(source["file_sha256"], []).append(source["artifact_id"])
    listed = {group["file_sha256"]: group["artifact_ids"] for group in dedup}
    if len(listed) != len(dedup) or listed != {sha: sorted(names) for sha, names in aliases.items()}:
        raise ExplorerError("invalid explorer export: dedup does not match sources")
    by_sha: dict[str, dict[str, Any]] = {}
    for report in reports:
        if report["file_sha256"] in by_sha:
            raise ExplorerError("invalid explorer export: more than one report for one file")
        if report["artifact_id"] not in aliases.get(report["file_sha256"], []):
            raise ExplorerError("invalid explorer export: report artifact_id is not a source of its file")
        by_sha[report["file_sha256"]] = report
    if set(by_sha) != set(aliases):
        raise ExplorerError("invalid explorer export: a file has no report")
    return {"sources": sources, "dedup": dedup, "reports": reports}


def _parse_int(token: str) -> int:
    try:
        return int(token)
    except ValueError:  # Python's integer-string digit limit; not a JSONDecodeError
        raise ExplorerError("invalid explorer export: not valid JSON") from None


def _load_export(data_path: Path) -> dict[str, Any]:
    try:
        if data_path.stat().st_size > MAX_EXPORT_BYTES:
            raise ExplorerError("invalid explorer export: file exceeds the size limit")
        raw = data_path.read_bytes()
    except OSError:
        raise ExplorerError("cannot read the export file") from None
    try:
        text = raw.decode("utf-8")
        root = json.loads(
            text, object_pairs_hook=_no_duplicate_keys, parse_constant=_refuse_constant, parse_int=_parse_int
        )
    except UnicodeDecodeError:
        raise ExplorerError("invalid explorer export: not UTF-8 text") from None
    except (json.JSONDecodeError, RecursionError):
        raise ExplorerError("invalid explorer export: not valid JSON") from None
    return _validate(root)


def _publish_staged_directory(staging: Path, out_dir: Path) -> None:
    """Rename a complete sibling directory without replacing any existing entry."""
    if sys.platform not in {"linux", "darwin"}:
        raise OSError(errno.ENOSYS, "atomic directory publication unavailable")
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        operation = getattr(libc, "renamex_np", None)
        arguments = (os.fsencode(staging), os.fsencode(out_dir), 0x4)  # RENAME_EXCL
        argument_types = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    else:
        operation = getattr(libc, "renameat2", None)
        arguments = (-100, os.fsencode(staging), -100, os.fsencode(out_dir), 1)  # AT_FDCWD, RENAME_NOREPLACE
        argument_types = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    if operation is None:
        raise OSError(errno.ENOSYS, "atomic directory publication unavailable")
    operation.argtypes = argument_types
    operation.restype = ctypes.c_int
    if operation(*arguments) != 0:
        raise OSError(ctypes.get_errno() or errno.EIO, "directory publication failed")


def _write_atomically(out_dir: Path, page: str) -> Path:
    """Publish a fully staged directory exclusively; clean up only the owned staging directory."""
    staging = None
    try:
        parent = out_dir.parent
        parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}.", suffix=".staging", dir=parent))
        with (staging / PAGE_NAME).open("x", encoding="utf-8") as handle:
            handle.write(page)
        _publish_staged_directory(staging, out_dir)
        staging = None
        return out_dir / PAGE_NAME
    except OSError as exc:
        if exc.errno in {errno.EEXIST, errno.ENOTEMPTY}:
            raise ExplorerError("output directory already exists; choose a new --out path") from None
        raise ExplorerError("cannot publish explorer output; choose a writable --out path") from None
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def render_explorer(data_path: Path, out_dir: Path) -> Path:
    """Validate one comparison export and write a self-contained ``index.html`` into a new directory.

    Input validation and rendering finish before output publication begins. Filesystem
    failures may leave newly created parent directories; owned staging is cleaned up.
    Returns the page path after publishing the complete output directory.
    """
    export = _load_export(Path(data_path))
    page = _render_page(export)
    return _write_atomically(Path(out_dir), page)


_METRIC_GROUPS = (
    ("detection", "Images and detections"),
    ("strangers", "Named and stranger faces"),
    ("grouping", "Grouping"),
)
# (group, key, label, unit, glossary id). Every key is answered by _value below.
_METRIC_ROWS = (
    ("detection", "images-scored", "Images scored", "images", "images-scored"),
    ("detection", "images-failed", "Images that failed", "images", "images-failed"),
    ("detection", "faces-matched", "Faces matched", "faces", "faces-matched"),
    ("detection", "faces-missed", "Faces missed", "labelled faces", "faces-missed"),
    ("detection", "extra-detections", "Extra detections", "detected boxes", "extra-detections"),
    ("detection", "detection-precision", "Detection precision", "share of boxes", "detection-precision"),
    ("detection", "detection-recall", "Detection recall", "share of labelled faces", "detection-recall"),
    ("strangers", "named-faces", "Named faces matched", "faces", "named-faces"),
    ("strangers", "stranger-faces", "Stranger faces matched", "faces", "stranger-faces"),
    ("strangers", "strangers-rejected", "Strangers rejected", "strangers tested", "strangers-rejected"),
    ("grouping", "merge-rate", "Merge rate", "share of same-cluster pairs", "merge-rate"),
    ("grouping", "split-rate", "Split rate", "share of same-person pairs", "split-rate"),
    ("grouping", "cluster-purity", "Cluster purity", "recorded value, 0 to 1", "cluster-purity"),
    ("grouping", "grouped-faces", "Grouped faces", "faces", "grouped-faces"),
    ("grouping", "cluster-count", "Clusters", "clusters", "cluster-count"),
    ("grouping", "cluster-settings", "Clustering setting d_cut", "cosine distance, 1 − similarity", "cluster-settings"),
)
_METHODS = (
    (
        "in-tree",
        "HDBSCAN",
        "Code in this tree: production adapter. The firbench grouping path records it as metadata and does not run it.",
        "Euclidean metric (adapter default). Settings: minimum cluster size, minimum samples, selection epsilon.",
        "None attributed. No historical file records an HDBSCAN result.",
    ),
    (
        "in-tree",
        "Average-link HAC (cosine)",
        "Code in this tree: current analysis reference, average linkage.",
        "Cosine distance, cut at 1 − similarity.",
        "None attributed. No historical file records this method.",
    ),
    (
        "in-tree",
        "Complete-link HAC (cosine)",
        "Code in this tree: current analysis reference, complete linkage.",
        "Cosine distance, cut at 1 − similarity.",
        "None attributed. No historical file records this method.",
    ),
    (
        "in-tree",
        "Constrained HAC",
        "Code in this tree: production code (constrained_hac.py). Default linkage is median.",
        "Distance metric needs review before any result is attributed to it.",
        "None attributed.",
    ),
    (
        "other",
        "Chinese Whispers",
        "Archived code is known. Removed from this tree; not executed here.",
        "Not recorded.",
        "None attributed.",
    ),
    (
        "other",
        "DBSCAN",
        "Not located in the bounded current snapshot. Recovery is needed; this is not evidence that it was never implemented.",
        "Not recorded.",
        "None attributed.",
    ),
    (
        "other",
        "Threshold settings (d_cut) in historical files",
        "The method that used the threshold is not recorded, so the method is unknown.",
        "d_cut is shown per file in the table where a file records it.",
        "Shown per file, never copied to a method.",
    ),
)
_GLOSSARY = (
    (
        "historical-result",
        "Historical result",
        "history, historic, recorded",
        "A count or rate read from a report file recorded before this page. It describes that file. It is not a winner, a ranking, a hypothesis result or a gate.",
    ),
    (
        "report-file",
        "Report file",
        "file, digest, sha256",
        "One historical report file, identified by its SHA-256 digest. Two source names with one digest are one file.",
    ),
    (
        "partial-provenance",
        "Partial provenance",
        "provenance, commit, manifest",
        "Some source fields are not recorded for a file, such as its source commit or manifest hash. The page shows them as not recorded and does not fill them in.",
    ),
    (
        "not-recorded",
        "Not recorded",
        "null, missing, absent",
        "A numeric value is unavailable in this export. Source status is not exported: the original source may omit or refuse the value. This is not zero; zero is a recorded number. For source metadata, not recorded means the exported field is missing.",
    ),
    (
        "compatibility-unknown",
        "Compatibility unknown",
        "compatibility, comparable, like for like",
        "Whether two files used the same detected population, thresholds, model weights, templates and gallery pins. Unknown means the file does not record enough to check, so the columns are not a like-for-like comparison.",
    ),
    (
        "pipeline",
        "Pipeline",
        "pipeline, leg, detector, embedder",
        "The recognition pipeline as one leg: detector, alignment, embedder, gallery and scorer. A difference between pipelines can come from any of these parts, not from the embedder alone.",
    ),
    (
        "sface",
        "SFace",
        "sface, ort-yunet-sface, 128",
        "The SFace pipeline. Its embedding model is ort-yunet-sface, with 128 dimensions.",
    ),
    (
        "insightface",
        "InsightFace",
        "insightface, buffalo_l, 512",
        "The InsightFace pipeline. Its embedding model is buffalo_l, with 512 dimensions.",
    ),
    (
        "auraface",
        "AuraFace",
        "auraface, 512",
        "The AuraFace pipeline, configured with 512-dimensional embeddings. Its column shows a result only when the export includes an AuraFace report file; otherwise the column says No result.",
    ),
    (
        "images-scored",
        "Images scored",
        "images, scored",
        "Images in the file that were scored, shown with the total images in the file.",
    ),
    ("images-failed", "Images that failed", "failed, failures", "Images in the file that could not be scored."),
    (
        "faces-matched",
        "Faces matched",
        "matched, tp, true positive",
        "Detected boxes that matched a labelled face at the IoU threshold (true positives, tp). The export carries this count as matched faces.",
    ),
    (
        "faces-missed",
        "Faces missed",
        "missed, fn, false negative",
        "Labelled faces with no detected box at the IoU threshold (false negatives, fn). The labelled total shown is matched plus missed.",
    ),
    (
        "extra-detections",
        "Extra detections",
        "extra, fp, false positive",
        "Detected boxes that overlap no labelled face (fp).",
    ),
    (
        "detection-precision",
        "Detection precision",
        "precision",
        "tp ÷ (tp + fp): the share of detected boxes that matched a labelled face.",
    ),
    (
        "detection-recall",
        "Detection recall",
        "recall",
        "tp ÷ (tp + fn): the share of labelled faces that a detected box matched.",
    ),
    (
        "iou-threshold",
        "IoU threshold",
        "iou, overlap",
        "Intersection over union: the overlap between a detected box and a labelled face, from 0 to 1. A detection matches when its overlap reaches the threshold. This export does not record the threshold value.",
    ),
    ("named-faces", "Named faces matched", "named", "Matched faces whose labelled person has a name in the probe set."),
    (
        "stranger-faces",
        "Stranger faces matched",
        "stranger, unnamed",
        "Matched faces whose labelled person has no name in the probe set. These are matched detections. They are not rejections or false accepts.",
    ),
    (
        "strangers-rejected",
        "Strangers rejected",
        "rejected, unknown, stranger rejection",
        "Stranger faces the system correctly did not match to anyone, out of all stranger faces tested. The total n is correct rejects plus false accepts plus stranger faces the detector missed.",
    ),
    (
        "merge-rate",
        "Merge rate",
        "merge, false merge",
        "False merges ÷ same-cluster pairs: pairs of different people placed in one cluster, divided by all pairs placed in one cluster (m_co_clustered).",
    ),
    (
        "split-rate",
        "Split rate",
        "split, false split",
        "False splits ÷ same-person pairs: pairs of one person placed in different clusters, divided by all same-person pairs (p_same).",
    ),
    (
        "cluster-purity",
        "Cluster purity",
        "purity",
        "Definition pending. The export carries a recorded purity value, but this page does not define its formula.",
    ),
    ("grouped-faces", "Grouped faces", "grouped, faces clustered", "Faces in the grouping sample (n_faces)."),
    ("cluster-count", "Clusters", "clusters, cluster count", "Clusters produced for the grouped faces (n_clusters)."),
    (
        "cluster-settings",
        "Clustering setting d_cut",
        "d_cut, cut, distance cut, settings",
        "The distance cut used for grouping, in cosine distance (1 − similarity). Where a file records the method, the page shows it; otherwise the method is not recorded.",
    ),
    ("cosine-distance", "Cosine distance", "cosine", "1 − cosine similarity between two embeddings."),
    (
        "threshold",
        "Acceptance threshold",
        "threshold, tau, τ",
        "The similarity score a face match must reach before the system accepts it.",
    ),
    (
        "hdbscan",
        "HDBSCAN",
        "hdbscan, density",
        "Density-based clustering. In this tree it is a production adapter; the firbench grouping path records it as metadata and does not run it.",
    ),
    (
        "average-link",
        "Average-link clustering",
        "average, average linkage, hac",
        "Hierarchical agglomerative clustering that measures the distance between two groups by the average distance between their members.",
    ),
    (
        "complete-link",
        "Complete-link clustering",
        "complete, complete linkage, hac",
        "Hierarchical agglomerative clustering that measures the distance between two groups by the farthest pair of their members.",
    ),
    (
        "constrained-hac",
        "Constrained HAC",
        "constrained, median, linkage",
        "Hierarchical agglomerative clustering with pairwise identity constraints (constrained_hac.py). Its default linkage is median. Its distance metric needs review before any result is attributed to it.",
    ),
    (
        "chinese-whispers",
        "Chinese Whispers",
        "chinese whispers, graph",
        "A graph clustering method. Archived code is known; it was removed from this tree and is not executed.",
    ),
    (
        "dbscan",
        "DBSCAN",
        "dbscan, density",
        "A density-based clustering method. It is not located in the bounded current snapshot. Recovery is needed; this page does not treat that as proof it was never implemented.",
    ),
    (
        "h1",
        "H1 (initial hypothesis)",
        "h1, superiority",
        "The first hypothesis: whether the model change is real at the primary operating point (FNIR at FPIR 0.01, end to end). It is not evaluated on this page.",
    ),
    (
        "h2",
        "H2 (second hypothesis)",
        "h2, non-inferiority",
        "The second hypothesis, a non-inferiority check between AuraFace and InsightFace with a margin of 0.05. It runs only after H1 passes. It is not evaluated on this page.",
    ),
    (
        "fnir",
        "FNIR (false negative identification rate)",
        "fnir",
        "Among searches for people who are enrolled, the share that do not end with the correct person accepted at the acceptance threshold τ.",
    ),
    (
        "fpir",
        "FPIR (false positive identification rate)",
        "fpir",
        "Definition pending. The manifest names this rate; this page does not define it.",
    ),
    (
        "guardrail",
        "Guardrail (G1 to G5)",
        "guardrail, g1, g2, g3, g4, g5",
        "A veto check in the committed manifest. Their rules are null there, so no pass or fail is declared. This page evaluates none of them.",
    ),
    (
        "g1",
        "G1 per-cohort FPIR",
        "g1, cohort, fpir",
        "A false-match rate per demographic group, over non-mated (stranger) source units. This export carries no cohort populations.",
    ),
    (
        "g2",
        "G2 false names per 1k mentions",
        "g2, false names",
        "Definition pending. The manifest names this guardrail; this page does not define its unit.",
    ),
    (
        "g3",
        "G3 worst pair-cell FNIR",
        "g3, pair cell, fnir",
        "Definition pending. The manifest names this guardrail; this page does not define the worst-pair-cell calculation.",
    ),
    (
        "g4",
        "G4 p95 time per face",
        "g4, p95, timing",
        "An allocated estimate, not a stopwatch: each expected ground-truth face is charged the whole native processing time of its image, divided by that image's ground-truth face count, plus an equal share of the time spent on images with no ground-truth faces. The 95th percentile is taken over those amounts.",
    ),
    ("g5", "G5 cost per accepted description", "g5, cost", "Report-only: a cost measure with no pass or fail rule."),
)
_CSS = """
:root { color-scheme: light dark; --bg: #ffffff; --fg: #1b1b1b; --muted: #545454; --line: #767676; --accent: #1f4e79; --sel: #dce8f5; --note-bg: #f4f4f4; }
@media (prefers-color-scheme: dark) { :root { --bg: #121212; --fg: #ececec; --muted: #b8b8b8; --line: #8a8a8a; --accent: #8fb8e8; --sel: #1f3347; --note-bg: #1e1e1e; } }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--fg); font: 1rem/1.5 system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
main { max-width: 72rem; margin: 0 auto; padding: 1rem; }
h1 { font-size: 1.75rem; line-height: 1.25; margin: .25rem 0 .5rem; }
h2 { font-size: 1.25rem; line-height: 1.3; margin: 2rem 0 .5rem; }
h3 { font-size: 1rem; margin: .25rem 0; }
p, li { max-width: 68ch; }
.kicker, .sub, .unit { color: var(--muted); font-size: .875rem; }
.sub, .unit { display: block; }
a { color: var(--accent); }
:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
[hidden] { display: none !important; }
.banner, .callout { border: 2px solid var(--fg); padding: .75rem 1rem; margin: 1rem 0; max-width: 68ch; }
.callout { background: var(--note-bg); }
.controls { display: flex; flex-wrap: wrap; gap: .75rem 1.25rem; align-items: flex-end; margin: 1rem 0 .5rem; }
.controls label, .variant-label { display: block; font-weight: 600; font-size: .875rem; margin-bottom: .25rem; }
select, input[type="search"] { font: inherit; min-height: 2.5rem; max-width: 100%; padding: .375rem .5rem; border: 1px solid var(--line); border-radius: 4px; background: var(--bg); color: var(--fg); }
input[type="search"]::placeholder { color: var(--muted); opacity: 1; }
button { font: inherit; min-height: 2.5rem; padding: .375rem .75rem; border: 2px solid var(--fg); border-radius: 4px; background: var(--bg); color: var(--fg); cursor: pointer; }
button:hover:not(:disabled) { background: var(--sel); }
button:disabled { border-color: var(--line); color: var(--muted); cursor: not-allowed; }
.status { color: var(--muted); font-size: .875rem; margin: .25rem 0; }
.table-wrap { overflow-x: auto; max-width: 100%; border: 1px solid var(--line); border-radius: 4px; }
table { border-collapse: collapse; width: 100%; min-width: 36rem; }
caption { text-align: left; padding: .5rem .75rem; color: var(--muted); font-size: .875rem; caption-side: top; }
th, td { padding: .5rem .75rem; border-bottom: 1px solid var(--line); vertical-align: top; text-align: left; }
th.num, td.num { text-align: right; font-variant-numeric: tabular-nums; }
th[scope="row"] { position: sticky; left: 0; background: var(--bg); min-width: 12rem; font-weight: 600; }
tbody tr:hover th, tbody tr:hover td { background: var(--sel); }
.nr, .none { color: var(--muted); font-style: italic; font-weight: 400; }
.define { font-size: .875rem; font-weight: 400; }
.digest { display: block; overflow-x: auto; max-width: 100%; white-space: nowrap; font-size: .8125rem; }
code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: .875rem; }
pre { overflow-x: auto; max-width: 100%; padding: .5rem; border: 1px solid var(--line); background: var(--bg); }
details { margin: 1rem 0; max-width: 100%; }
summary { cursor: pointer; font-weight: 600; min-height: 2.5rem; padding: .5rem 0; }
.term { border-top: 1px solid var(--line); padding: .75rem 0; max-width: 68ch; }
.term:target { outline: 3px solid var(--accent); outline-offset: 4px; }
.methods th, .methods td { white-space: normal; }
.source-table td, .source-table th { font-size: .9375rem; }
@media (max-width: 40rem) { main { padding: .75rem; } h1 { font-size: 1.5rem; } }
"""
_SCRIPT = """
(function () {
  "use strict";
  var config = JSON.parse(document.getElementById("explorer-config").textContent);
  var query = new URLSearchParams(window.location.search);
  var status = document.getElementById("status");
  var focusSelect = document.getElementById("metric-focus");
  var methodSelect = document.getElementById("method-filter");
  var search = document.getElementById("term-search");
  var clearButton = document.getElementById("clear-filters");
  var emptyNote = document.getElementById("term-empty");
  var emptyQuery = document.getElementById("term-empty-query");
  var groups = Array.prototype.slice.call(document.querySelectorAll("tbody[data-group]"));
  var metricRows = Array.prototype.slice.call(document.querySelectorAll("tr[data-metric]"));
  var methodRows = Array.prototype.slice.call(document.querySelectorAll("tr[data-method]"));
  var terms = Array.prototype.slice.call(document.querySelectorAll("article[data-term]"));
  var values = Array.prototype.slice.call(document.querySelectorAll("span.val[data-pipeline]"));
  var pipelines = Object.keys(config.pipelines);

  function choose(name, allowed, fallback) {
    var value = query.get(name);
    return allowed.indexOf(value) >= 0 ? value : fallback;
  }
  pipelines.forEach(function (pipeline) {
    var select = document.getElementById("variant-" + pipeline);
    var wanted = query.get("variant-" + pipeline);
    if (select && config.pipelines[pipeline].indexOf(wanted) >= 0) { select.value = wanted; }
  });
  focusSelect.value = choose("focus", ["all", "detection", "strangers", "grouping"], "all");
  methodSelect.value = choose("methods", ["all", "in-tree", "other"], "all");
  search.value = query.get("q") || "";

  function writeState() {
    var params = new URLSearchParams();
    pipelines.forEach(function (pipeline) {
      var select = document.getElementById("variant-" + pipeline);
      if (select && select.value !== config.defaults[pipeline]) { params.set("variant-" + pipeline, select.value); }
    });
    if (focusSelect.value !== "all") { params.set("focus", focusSelect.value); }
    if (methodSelect.value !== "all") { params.set("methods", methodSelect.value); }
    var q = (help && help.q !== null ? help.q : search.value).trim();
    if (q) { params.set("q", q); }
    var text = params.toString();
    window.history.replaceState(null, "", window.location.pathname + (text ? "?" + text : "") + window.location.hash);
  }

  function apply() {
    values.forEach(function (span) {
      var select = document.getElementById("variant-" + span.getAttribute("data-pipeline"));
      span.hidden = !select || span.getAttribute("data-variant") !== select.value;
    });
    groups.forEach(function (group) {
      group.hidden = focusSelect.value !== "all" && group.getAttribute("data-group") !== focusSelect.value;
    });
    var shownRows = metricRows.filter(function (row) { return !row.parentElement.hidden; }).length;
    methodRows.forEach(function (row) {
      row.hidden = methodSelect.value !== "all" && row.getAttribute("data-method") !== methodSelect.value;
    });
    var shownMethods = methodRows.filter(function (row) { return !row.hidden; }).length;
    var needle = search.value.trim().toLowerCase();
    terms.forEach(function (term) {
      term.hidden = needle !== "" && term.getAttribute("data-term").indexOf(needle) < 0;
    });
    var shownTerms = terms.filter(function (term) { return !term.hidden; }).length;
    emptyNote.hidden = shownTerms > 0;
    emptyQuery.textContent = search.value.trim();
    clearButton.disabled = focusSelect.value === "all" && methodSelect.value === "all" && needle === "";
    status.textContent = "Showing " + shownRows + " of " + metricRows.length + " metric rows, " +
      shownMethods + " of " + methodRows.length + " grouping methods, and " +
      shownTerms + " of " + terms.length + " glossary terms.";
    if (help && help.q !== null) {
      status.textContent += ' Glossary search "' + help.q.trim() + '" is set aside while a definition is shown. ' +
        "Back to results restores it.";
    }
    writeState();
  }

  // Glossary help. A definition link remembers its caller. If the glossary search hides the
  // definition, the search is set aside, but kept in the URL, until the reader leaves the
  // definition. Return and browser Back then restore the search, unless the reader changed it
  // meanwhile, and put focus and scroll back on the caller. Without a visible caller, focus
  // goes to the results heading.
  var help = null;
  var returning = null;
  var resultsHead = document.getElementById("results-head");

  function termFor(hash) {
    var target = hash.length > 1 ? document.getElementById(hash.slice(1)) : null;
    return target && target.hasAttribute("data-term") ? target : null;
  }
  function startHelp(term, caller) {
    var hash = "#" + term.id;
    var held = help ? help.q : null;
    if (held === null && term.hidden && search.value.trim() !== "") { held = search.value; }
    var same = help !== null && help.hash === hash && location.hash === hash;
    help = {
      hash: hash, caller: caller, q: held,
      callerHref: same ? help.callerHref : location.href, pushed: same && help.pushed,
      x: window.scrollX, top: caller ? caller.getBoundingClientRect().top : 0,
    };
    if (held !== null) { search.value = ""; apply(); }
  }
  function keepManualSearch() {
    if (help) { help.q = null; }
  }
  function endHelp() {
    var ended = help;
    help = null;
    if (ended.q !== null) { search.value = ended.q; }
    apply();
    return ended;
  }
  function returnTo(ended) {
    var caller = ended.caller;
    if (caller && caller.isConnected && caller.getClientRects().length > 0) {
      caller.focus({ preventScroll: true });
      window.scrollTo(ended.x, window.scrollY + caller.getBoundingClientRect().top - ended.top);
    } else {
      resultsHead.setAttribute("tabindex", "-1");
      resultsHead.focus({ preventScroll: true });
      resultsHead.scrollIntoView();
    }
  }
  function backToResults(event, link) {
    var ended = endHelp();
    if (ended.caller && ended.pushed && location.hash === ended.hash) {
      // The definition is the history step after its caller: undo that step.
      event.preventDefault();
      returnTo(ended);
      returning = { href: ended.callerHref, ended: ended };
      window.history.back();
    } else {
      returning = { href: link.href, ended: ended };
    }
  }
  function navigated(event) {
    var back = returning;
    if (event.type === "hashchange" || (back && location.href !== back.href)) { returning = null; }
    if (back && location.href === back.href) { apply(); returnTo(back.ended); return; }
    if (help) {
      if (location.hash === help.hash) { help.pushed = true; return; }
      var ended = endHelp();
      if (ended.caller && location.href === ended.callerHref) {
        returnTo(ended);
        if (event.type === "popstate") { returning = { href: ended.callerHref, ended: ended }; }
        return;
      }
    }
    var term = termFor(location.hash);
    if (term) { startHelp(term, null); }
  }

  document.addEventListener("click", function (event) {
    if (event.defaultPrevented || event.button !== 0 ||
        event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) { return; }
    var link = event.target.closest ? event.target.closest("a[href^='#']") : null;
    if (!link) { return; }
    var href = link.getAttribute("href");
    if (href === "#results" && link.closest("article[data-term]")) {
      if (help) { backToResults(event, link); }
      return;
    }
    var term = termFor(href);
    if (term) { startHelp(term, link); }
  });
  window.addEventListener("popstate", navigated);
  window.addEventListener("hashchange", navigated);

  pipelines.forEach(function (pipeline) {
    document.getElementById("variant-" + pipeline).addEventListener("change", apply);
  });
  focusSelect.addEventListener("change", apply);
  methodSelect.addEventListener("change", apply);
  search.addEventListener("input", function () { keepManualSearch(); apply(); });
  search.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && search.value !== "") { event.preventDefault(); search.value = ""; apply(); }
  });
  clearButton.addEventListener("click", function () {
    focusSelect.value = "all";
    methodSelect.value = "all";
    search.value = "";
    keepManualSearch();
    apply();
    focusSelect.focus();
  });
  apply();
  var entry = termFor(location.hash);
  if (entry) { startHelp(entry, null); }
})();
"""


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _script_json(value: object) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=True)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _value(report: Mapping[str, Any], key: str) -> tuple[str, str] | None:
    """Return (value, detail) for one metric, or None when the file does not record it."""
    counts = report["counts"]
    detection = report["detection"]
    tp, fp, fn = detection["tp"], detection["fp"], detection["fn"]
    if key == "images-scored":
        if counts["scored"] is None:
            return None
        return str(counts["scored"]), (f"of {counts['total']} images" if counts["total"] is not None else "")
    if key == "images-failed":
        return None if counts["failed"] is None else (str(counts["failed"]), "")
    if key == "faces-matched":
        return None if counts["matched_faces"] is None else (str(counts["matched_faces"]), "")
    if key == "faces-missed":
        if fn is None:
            return None
        return str(fn), (f"of {tp + fn} labelled faces ({tp} matched + {fn} missed)" if tp is not None else "")
    if key == "extra-detections":
        return None if fp is None else (str(fp), "")
    if key == "detection-precision":
        if detection["precision"] is None:
            return None
        detail = f"{tp} ÷ ({tp} + {fp})" if tp is not None and fp is not None else ""
        return _percent(detection["precision"]), detail
    if key == "detection-recall":
        if detection["recall"] is None:
            return None
        detail = f"{tp} ÷ ({tp} + {fn})" if tp is not None and fn is not None else ""
        return _percent(detection["recall"]), detail
    if key == "named-faces":
        return None if counts["named_matched"] is None else (str(counts["named_matched"]), "")
    if key == "stranger-faces":
        return None if counts["stranger_matched"] is None else (str(counts["stranger_matched"]), "")
    if key == "strangers-rejected":
        block = report["unknown_rejection"]
        if block is None:
            return None
        correct, n, rate = block["correct_rejects"], block["n"], block["rate"]
        if correct is None and rate is None:
            return None
        rate_text = "rate not recorded" if rate is None else f"rate {_percent(rate)}"
        if correct is None:
            return _percent(rate), rate_text
        # A known count survives a missing denominator; it is never turned into a rate or a zero.
        if n is None:
            return str(correct), f"denominator not recorded; {rate_text}"
        return f"{correct} of {n}", rate_text
    clustering = report["clustering"]
    if clustering is None:
        return None
    if key == "merge-rate":
        if clustering["false_merge"] is None:
            return None
        m = clustering["m_co_clustered"]
        return _percent(clustering["false_merge"]), (f"over {m} same-cluster pairs" if m is not None else "")
    if key == "split-rate":
        if clustering["false_split"] is None:
            return None
        p_same = clustering["p_same"]
        return _percent(clustering["false_split"]), (f"over {p_same} same-person pairs" if p_same is not None else "")
    if key == "cluster-purity":
        if clustering["purity"] is None:
            return None
        return f"{clustering['purity']:.3f}", "definition pending"
    if key == "grouped-faces":
        return None if clustering["n_faces"] is None else (str(clustering["n_faces"]), "")
    if key == "cluster-count":
        return None if clustering["n_clusters"] is None else (str(clustering["n_clusters"]), "")
    if key == "cluster-settings":
        if clustering["d_cut"] is None:
            return None
        method = clustering["algorithm"] or "method not recorded"
        return f"{clustering['d_cut']:.3f}", f"cosine distance; {method}"
    raise KeyError(key)


def _cell(pipeline: str, variants: list[dict[str, Any]], key: str) -> str:
    if not variants:
        return '<td class="num"><span class="none">No result</span></td>'
    spans = []
    for index, report in enumerate(variants):
        value = _value(report, key)
        hidden = "" if index == 0 else " hidden"
        if value is None:
            body = '<span class="nr">unavailable in this export (not recorded here)</span>'
        else:
            text, detail = value
            body = _esc(text) + (f'<span class="sub">{_esc(detail)}</span>' if detail else "")
        spans.append(
            f'<span class="val" data-pipeline="{pipeline}" data-variant="{_esc(report["artifact_id"])}"{hidden}>{body}</span>'
        )
    return '<td class="num">' + "".join(spans) + "</td>"


def _variant_select(pipeline: str, variants: list[dict[str, Any]]) -> str:
    options = "".join(
        f'<option value="{_esc(item["artifact_id"])}">{_esc(item["artifact_id"])}</option>' for item in variants
    )
    return (
        f'<label class="variant-label" for="variant-{pipeline}">Report file</label>'
        f'<select id="variant-{pipeline}">{options}</select>'
    )


def _header_cell(pipeline: str, variants: list[dict[str, Any]]) -> str:
    name = PIPELINE_LABELS[pipeline]
    if not variants:
        return (
            f'<th scope="col" class="num"><span class="col-name">{name}</span>'
            '<span class="sub">No result in the selected set</span></th>'
        )
    detail = f'<span class="sub">{len(variants)} file(s) for this pipeline</span>' if len(variants) > 1 else ""
    return f'<th scope="col" class="num"><span class="col-name">{name}</span>{detail}{_variant_select(pipeline, variants)}</th>'


def _metric_table(variants: Mapping[str, list[dict[str, Any]]]) -> str:
    head = "".join(_header_cell(pipeline, variants[pipeline]) for pipeline in PIPELINE_ORDER)
    bodies = []
    for group, title in _METRIC_GROUPS:
        rows = []
        for row_group, key, label, unit, term in _METRIC_ROWS:
            if row_group != group:
                continue
            cells = "".join(_cell(pipeline, variants[pipeline], key) for pipeline in PIPELINE_ORDER)
            rows.append(
                f'<tr data-metric="{key}"><th scope="row">{_esc(label)}<span class="unit">{_esc(unit)}</span>'
                f'<a class="define" href="#term-{term}">What does this mean?</a></th>{cells}</tr>'
            )
        bodies.append(
            f'<tbody data-group="{group}"><tr class="group"><th colspan="4" scope="colgroup">{_esc(title)}</th></tr>{"".join(rows)}</tbody>'
        )
    return (
        '<div class="table-wrap"><table>'
        "<caption>Historical results by pipeline. Each value comes from the report file selected above its column. "
        'Under a value, its count or denominator. Numeric nulls are unavailable in this export. For numeric counts, denominators and rates, "not recorded" means not recorded in this export. Source status is not exported: the original source may omit or refuse the value.</caption>'
        f'<thead><tr><th scope="col">Metric</th>{head}</tr></thead>{"".join(bodies)}</table></div>'
    )


def _source_table(export: Mapping[str, Any]) -> str:
    rows = []
    for source in export["sources"]:
        pins = []
        for field, is_digest in (("source_sha", True), ("manifest_sha256", True), ("manifest_hash_kind", False)):
            value = source[field]
            if value is None:
                pins.append('<td><span class="nr">not recorded</span></td>')
            elif is_digest:
                pins.append(f'<td><code class="digest">{_esc(value)}</code></td>')
            else:
                pins.append(f"<td>{_esc(value)}</td>")
        rows.append(
            "<tr>"
            f'<th scope="row">{_esc(source["artifact_id"])}</th>'
            f'<td><code class="digest">{_esc(source["file_sha256"])}</code></td>'
            f"<td>{_esc(source['kind'])}</td>"
            f"<td>{_esc(source['qualification'])}</td>"
            f"{''.join(pins)}"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="source-table">'
        "<caption>Each source entry as the export records it: canonical artifact ID, file digest, kind, qualification, "
        "source commit, manifest hash and manifest hash kind.</caption>"
        '<thead><tr><th scope="col">Artifact ID</th><th scope="col">File SHA-256</th><th scope="col">Kind</th>'
        '<th scope="col">Qualification</th><th scope="col">Source commit</th><th scope="col">Manifest hash</th>'
        '<th scope="col">Manifest hash kind</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _provenance_summary(export: Mapping[str, Any]) -> str:
    """Count each provenance field per source entry; a gap in one entry is never reported for the whole export."""
    sources = export["sources"]
    total = len(sources)
    if total:
        commits, manifests, kinds = (
            sum(source[field] is not None for source in sources)
            for field in ("source_sha", "manifest_sha256", "manifest_hash_kind")
        )
        counts = (
            f"Recorded provenance: source commit for {commits} of {total} source {'entry' if total == 1 else 'entries'}, "
            f"manifest hash for {manifests} of {total} and manifest hash kind for {kinds} of {total}. "
            "Each row shows its own values; not recorded applies only to that entry and field. "
        )
    else:
        counts = "This export lists no source entries, so it records no source commit or manifest hash. "
    return (
        f'<p class="sub">{counts}'
        "Recorded values are copied from the export as declared; this page has not verified them. "
        "It does not check that the files used the same inputs, model weights, templates or gallery, "
        "and a recorded pin does not make any file a winner. "
        "The original report files are not linked here. Their paths are never part of this page.</p>"
    )


def _method_table() -> str:
    rows = "".join(
        f'<tr data-method="{klass}"><th scope="row">{_esc(name)}</th><td>{_esc(status)}</td>'
        f"<td>{_esc(settings)}</td><td>{_esc(numbers)}</td></tr>"
        for klass, name, status, settings, numbers in _METHODS
    )
    return (
        '<div class="table-wrap methods"><table>'
        "<caption>Availability and settings only. These rows are not scores, and no historical number is attributed to a method.</caption>"
        '<thead><tr><th scope="col">Method</th><th scope="col">Availability in this tree</th>'
        '<th scope="col">Settings and distance</th><th scope="col">Historical numbers</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></div>"
    )


def _glossary() -> str:
    items = []
    for term_id, label, aliases, definition in sorted(_GLOSSARY, key=lambda item: item[1].lower()):
        search_text = f"{label} {aliases}".lower()
        items.append(
            f'<article class="term" id="term-{term_id}" data-term="{_esc(search_text)}">'
            f"<h3>{_esc(label)}</h3><p>{_esc(definition)}</p>"
            '<p class="sub"><a href="#results">Back to results</a></p></article>'
        )
    return "".join(items)


def _intake_callout(variants: Mapping[str, list[dict[str, Any]]]) -> str:
    if variants["auraface"]:
        return ""
    return (
        '<section id="auraface-intake" class="callout" aria-labelledby="auraface-head">'
        '<h3 id="auraface-head">No AuraFace result in the selected set</h3>'
        "<p>This page covers only the files registered for this set. To add an AuraFace report:</p>"
        "<ol>"
        "<li>Register its report file. The file stays where it is, and this page never shows its path:"
        "<pre><code>python -m scripts.eval_harness.firbench_cli evidence register &lt;artifact-id&gt; "
        "--evidence-db &lt;evidence.sqlite&gt; --kind report-json --path &lt;path-to-report.json&gt;</code></pre></li>"
        "<li>Check the pointer:"
        "<pre><code>python -m scripts.eval_harness.firbench_cli evidence check &lt;artifact-id&gt; "
        "--evidence-db &lt;evidence.sqlite&gt;</code></pre></li>"
        "<li>Regenerate the comparison export from the evidence database, then render it again:"
        "<pre><code>python -m scripts.eval_harness.firbench_cli explore --data &lt;export.json&gt; "
        "--out &lt;new-directory&gt;</code></pre></li>"
        "</ol></section>"
    )


def _summary(export: Mapping[str, Any], variants: Mapping[str, list[dict[str, Any]]]) -> str:
    files = len(export["reports"])
    names = len(export["sources"])
    parts = []
    for pipeline in PIPELINE_ORDER:
        count = len(variants[pipeline])
        parts.append(
            f"{PIPELINE_LABELS[pipeline]} ({count} file{'s' if count != 1 else ''})"
            if count
            else f"{PIPELINE_LABELS[pipeline]} (no result in this set)"
        )
    return (
        f'<p class="summary">{names} source entries name {files} distinct files, by SHA-256 digest. '
        f"Pipelines with a file: {_esc(', '.join(parts))}. "
        "These are descriptive historical counts, read as recorded. The files are not "
        f"{files} independent runs, and nothing on this page names a winner.</p>"
    )


def _same_count_notes(variants: Mapping[str, list[dict[str, Any]]]) -> str:
    notes = []
    for pipeline in PIPELINE_ORDER:
        group = variants[pipeline]
        if len(group) > 1:
            notes.append(
                f"<li>{PIPELINE_LABELS[pipeline]} has {len(group)} files with different digests. "
                "Equal counts do not show that two files used the same images.</li>"
            )
    return f"<ul>{''.join(notes)}</ul>" if notes else ""


def _render_page(export: Mapping[str, Any]) -> str:
    variants: dict[str, list[dict[str, Any]]] = {pipeline: [] for pipeline in PIPELINE_ORDER}
    unplaced = 0
    for report in sorted(export["reports"], key=lambda item: item["artifact_id"]):
        if report["pipeline"] is None:
            unplaced += 1
        else:
            variants[report["pipeline"]].append(report)
    config = {
        "pipelines": {p: [r["artifact_id"] for r in variants[p]] for p in PIPELINE_ORDER if variants[p]},
        "defaults": {p: variants[p][0]["artifact_id"] for p in PIPELINE_ORDER if variants[p]},
    }
    unplaced_note = (
        f'<p class="status">{unplaced} file(s) have no known pipeline and are not placed in a column. '
        "Their digests are listed under Source evidence.</p>"
        if unplaced
        else ""
    )
    focus_options = "".join(
        f'<option value="{value}">{label}</option>'
        for value, label in (
            ("all", "All metrics"),
            ("detection", "Images and detections"),
            ("strangers", "Named and stranger faces"),
            ("grouping", "Grouping"),
        )
    )
    method_options = "".join(
        f'<option value="{value}">{label}</option>'
        for value, label in (
            ("all", "All methods"),
            ("in-tree", "Code in this tree"),
            ("other", "No code here or unknown"),
        )
    )
    body = (
        '<p class="kicker">FIRBENCH-1 comparison explorer</p>'
        "<h1>Historical results</h1>"
        f"{_summary(export, variants)}"
        '<section class="banner" aria-labelledby="compat-head">'
        '<h2 id="compat-head">Compatibility unknown</h2>'
        "<p>These files do not record enough to check that they used the same detected population, thresholds, "
        "model weights, templates or gallery pins. Read the columns as separate historical results, not as a "
        'like-for-like test. <a href="#term-compatibility-unknown">What does compatibility mean?</a></p>'
        "</section>"
        '<section id="results" aria-labelledby="results-head">'
        '<h2 id="results-head">Results by pipeline</h2>'
        "<p>How to read this: each value comes from one report file, listed under Source evidence. "
        "Rates show their counts under the value. A missing value is not zero.</p>"
        f"{_same_count_notes(variants)}"
        f"{unplaced_note}"
        '<div class="controls" role="group" aria-label="Choose what to show">'
        f'<div><label for="metric-focus">Metric focus</label><select id="metric-focus">{focus_options}</select></div>'
        '<div><label for="term-search">Search glossary terms</label>'
        '<input type="search" id="term-search" autocomplete="off" placeholder="for example: missed"></div>'
        f'<div><label for="method-filter">Grouping methods</label><select id="method-filter">{method_options}</select></div>'
        '<div><button type="button" id="clear-filters" disabled>Clear search and focus</button></div>'
        "</div>"
        '<p id="status" class="status" role="status" aria-live="polite"></p>'
        f"{_metric_table(variants)}"
        f"{_intake_callout(variants)}"
        "</section>"
        '<section aria-labelledby="methods-head"><h2 id="methods-head">Grouping methods: availability</h2>'
        "<p>These rows say what code exists in this tree. They are not measured scores, and the historical files do not name the method that produced them.</p>"
        f"{_method_table()}</section>"
        '<section aria-labelledby="notes-head"><h2 id="notes-head">What this page does not evaluate</h2>'
        "<ul><li>H1 (initial hypothesis) and H2 (second, only after H1 passes) are not evaluated here. "
        'Descriptive counts are not hypothesis results. <a href="#term-h1">H1</a>, <a href="#term-h2">H2</a>.</li>'
        "<li>Guardrails G1 to G5 are not evaluated. Their rules are null in the committed manifest, so no pass or fail is declared. "
        '<a href="#term-guardrail">Guardrails</a>.</li>'
        '<li>G4 timing is an allocated estimate per expected face, not a stopwatch. <a href="#term-g4">G4</a>.</li></ul></section>'
        '<details id="source-evidence"><summary>Source evidence and provenance</summary>'
        f"{_source_table(export)}"
        f"{_provenance_summary(export)}"
        "<details><summary>Source keys for code readers</summary><ul>"
        "<li>Images scored: counts.scored of counts.total</li>"
        "<li>Faces matched: counts.matched_faces (detection.tp)</li>"
        "<li>Faces missed and extra detections: detection.fn and detection.fp</li>"
        "<li>Detection precision and recall: detection.precision and detection.recall</li>"
        "<li>Named and stranger faces: counts.named_matched and counts.stranger_matched</li>"
        "<li>Strangers rejected: unknown_rejection.correct_rejects, n, rate</li>"
        "<li>Merge and split: clustering.false_merge (over m_co_clustered) and clustering.false_split (over p_same)</li>"
        "<li>Grouping setting: clustering.parameters.d_cut, clustering.algorithm, clustering.metric</li></ul></details></details>"
        '<section id="glossary" aria-labelledby="glossary-head"><h2 id="glossary-head">Glossary</h2>'
        '<p id="term-empty" hidden>No glossary term matches "<span id="term-empty-query"></span>". '
        "Use Clear search and focus to show every term.</p>"
        f'<div class="terms">{_glossary()}</div></section>'
    )
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; script-src 'unsafe-inline'; "
        "style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'\">"
        '<meta name="referrer" content="no-referrer">'
        "<title>Historical results: FIRBENCH-1 comparison explorer</title>"
        f"<style>{_CSS}</style></head>"
        f'<body><main id="top">{body}</main>'
        f'<script type="application/json" id="explorer-config">{_script_json(config)}</script>'
        f"<script>{_SCRIPT}</script></body></html>\n"
    )
