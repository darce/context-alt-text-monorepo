"""UX comparison explorer export: a bounded, descriptive projection of registered historical face reports.

Reads one registered ``acx-eval/v1`` ``face_bakeoff`` report per unique canonical file SHA-256 and writes
``firbench/comparison-explorer-export-v1``. This is limited historical exploration, not the full runner: it runs
no inference, ranks no models, and reads no private corpus table, image, or pseudonym. Artifact IDs go through the
evidence pointer API (``show``, ``check``, ``resolve``) only. Every exported value comes from a fixed whitelist of
numeric fields. A missing or refused measurement is ``null``, never zero. Each report carries
``compatibility: unknown`` and the pointer's own qualification, with no winner, delta, or acceptance field.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import math
import os
import re
import secrets
import stat
from collections.abc import Sequence
from pathlib import Path

from scripts.eval_harness import firbench_evidence
from scripts.eval_harness.firbench_contract import FirBenchError

SCHEMA = "firbench/comparison-explorer-export-v1"
SCHEMA_VERSION = 1
SOURCE_SCHEMA = "acx-eval/v1"
SOURCE_KIND = "report"
SOURCE_REPORT_KIND = "face_bakeoff"
POINTER_KIND = "report-json"
MAX_SOURCE_BYTES = 16 << 20
READ_CHUNK = 1 << 20
MAX_ARTIFACT_IDS = 64
MAX_COUNT = (1 << 31) - 1
MAX_EMBEDDING_DIM = 4096
# The three model IDs the historical reports were observed with. Any other string is exported as null.
MODEL_PIPELINES = {"ort-yunet-sface": "sface", "buffalo_l": "insightface", "auraface": "auraface"}
# Fixed known names only, in sorted order. Occlusion and demographic cohort rows are free-category and omitted.
SLICE_SECTIONS = ("clustering", "full_corpus_identification", "headline_identification", "unknown_rejection")
SOURCE_FIELDS = (
    "artifact_id",
    "file_sha256",
    "kind",
    "manifest_hash_kind",
    "manifest_sha256",
    "qualification",
    "source_sha",
)
REPORT_FIELDS = (
    "artifact_id",
    "clustering",
    "compatibility",
    "counts",
    "detection",
    "embedding_dim",
    "file_sha256",
    "identification",
    "model_id",
    "pipeline",
    "qualification",
    "slice_sections",
    "unknown_rejection",
)
COUNT_FIELDS = ("total", "scored", "failed", "matched_faces", "named_matched", "stranger_matched")
DETECTION_COUNTS = ("tp", "fn", "fp")
DETECTION_RATES = ("precision", "recall")
UNKNOWN_COUNTS = ("correct_rejects", "false_accepts", "n", "n_floor", "rate_numerator", "rate_denominator")
UNKNOWN_RATES = ("rate",)
CLUSTER_COUNTS = ("m_co_clustered", "n_clusters", "n_faces", "p_diff", "p_same")
CLUSTER_RATES = ("false_merge", "false_split", "purity")
IDENTIFICATION_COUNTS = (
    "fn",
    "fp",
    "missed_gt",
    "n_floor",
    "n_named_probes",
    "n_recall_eligible",
    "precision_denominator",
    "precision_numerator",
    "recall_denominator",
    "recall_numerator",
    "tp",
    "unmatched_detections",
)
IDENTIFICATION_RATES = ("precision", "recall")
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SHA40_RE = re.compile(r"[0-9a-f]{40}")
# Fixed texts. Refusals never carry a path, a label, a SQL value, or a source string.
_ID_INVALID = "artifact ID must be 1-128 ASCII letters, digits, '.', '_' or '-', starting with a letter or digit"
_ID_LIST = "artifact IDs must be a non-empty list of strings"
_TOO_MANY_IDS = f"at most {MAX_ARTIFACT_IDS} artifact IDs can be exported at once"
_NOT_REPORT_POINTER = "artifact must be a registered report-json pointer"
_SOURCE_REFUSED = "artifact is not an acx-eval/v1 face_bakeoff report"
_SOURCE_MALFORMED = "artifact report has a malformed field"
_SOURCE_NOT_JSON = "artifact report is not strict JSON"
_SOURCE_TOO_LARGE = "artifact report exceeds the 16 MiB bound"
_SOURCE_NOT_REGULAR = "artifact report must be a regular file"
_SOURCE_UNREADABLE = "artifact report is unreadable"
_SOURCE_CHANGED = "artifact report changed while it was being read"
_SOURCE_MISMATCH = "artifact report bytes do not match the registered SHA-256"
_STATUS_MISSING = "artifact file is missing"
_STATUS_CHANGED = "artifact changed since registration"
_OUTPUT_EXISTS = "output path already exists; refusing to overwrite"
_OUTPUT_UNWRITABLE = "output could not be written"
_PAYLOAD_INVALID = "export payload failed validation"


class ComparisonExportError(FirBenchError):
    """Fixed-text refusal for the comparison explorer export."""


# --- strict input decoding -------------------------------------------------------------------------


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    obj: dict[str, object] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate key")
        obj[key] = value
    return obj


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("number overflows to a non-finite value")
    return value


def _reject_constant(token: str) -> float:
    raise ValueError("non-finite constant")


def _parse_strict(raw: bytes) -> object:
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object_without_duplicates,
            parse_float=_finite_float,
            parse_constant=_reject_constant,
        )
    except (ValueError, RecursionError):
        raise ComparisonExportError(_SOURCE_NOT_JSON) from None


# --- value projection: absent or refused is null, never zero ---------------------------------------


def _check_artifact_id(value: object) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise ComparisonExportError(_ID_INVALID)
    return value


def _mapping(value: object) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ComparisonExportError(_SOURCE_MALFORMED)
    return value


def _section(slices: dict, name: str) -> dict | None:
    return _mapping(slices.get(name))


def _live(section: dict | None) -> dict | None:
    """The section's values, or None when it is absent or flagged refused."""
    if section is None:
        return None
    refused = section.get("refused", False)
    if type(refused) is not bool:
        raise ComparisonExportError(_SOURCE_MALFORMED)
    return None if refused else section


def _count_or_none(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= MAX_COUNT:
        raise ComparisonExportError(_SOURCE_MALFORMED)
    return value


def _real_or_none(value: object) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float):
        raise ComparisonExportError(_SOURCE_MALFORMED)
    try:
        number = float(value)
    except OverflowError:
        raise ComparisonExportError(_SOURCE_MALFORMED) from None
    if not math.isfinite(number):
        raise ComparisonExportError(_SOURCE_MALFORMED)
    return number


def _rate_or_none(value: object) -> float | None:
    number = _real_or_none(value)
    if number is not None and not 0.0 <= number <= 1.0:
        raise ComparisonExportError(_SOURCE_MALFORMED)
    return number


def _nonnegative_or_none(value: object) -> float | None:
    number = _real_or_none(value)
    if number is not None and number < 0.0:
        raise ComparisonExportError(_SOURCE_MALFORMED)
    return number


def _dimension_or_none(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 1 <= value <= MAX_EMBEDDING_DIM:
        raise ComparisonExportError(_SOURCE_MALFORMED)
    return value


def _numbers(section: dict | None, counts: Sequence[str], rates: Sequence[str]) -> dict[str, object]:
    live = _live(section)
    values: dict[str, object] = {}
    for name in counts:
        values[name] = None if live is None else _count_or_none(live.get(name))
    for name in rates:
        values[name] = None if live is None else _rate_or_none(live.get(name))
    return values


def _model_identity(root: dict) -> tuple[str | None, str | None, int | None]:
    """Legacy top-level ``model`` block, else the current ``provenance.model`` lists. Unknown IDs are null."""
    block = _mapping(root.get("model"))
    if block is not None:
        model_id = block.get("model_id")
        dimension = block.get("embedding_dim")
    else:
        provenance = _mapping(root.get("provenance")) or {}
        block = _mapping(provenance.get("model")) or {}
        ids = block.get("model_ids")
        dims = block.get("embedding_dims")
        model_id = ids[0] if isinstance(ids, list) and len(ids) == 1 else None
        dimension = dims[0] if isinstance(dims, list) and len(dims) == 1 else None
    if not isinstance(model_id, str) or model_id not in MODEL_PIPELINES:
        model_id = None
    pipeline = None if model_id is None else MODEL_PIPELINES[model_id]
    return model_id, pipeline, _dimension_or_none(dimension)


def summarize_legacy_report(raw: bytes, *, artifact_id: str) -> dict:
    """Project one historical ``acx-eval/v1`` ``face_bakeoff`` report onto the fixed export shape."""
    _check_artifact_id(artifact_id)
    if not isinstance(raw, bytes):
        raise ComparisonExportError(_SOURCE_MALFORMED)
    if len(raw) > MAX_SOURCE_BYTES:
        raise ComparisonExportError(_SOURCE_TOO_LARGE)
    root = _parse_strict(raw)
    if (
        not isinstance(root, dict)
        or root.get("schema") != SOURCE_SCHEMA
        or root.get("kind") != SOURCE_KIND
        or root.get("report_kind") != SOURCE_REPORT_KIND
    ):
        raise ComparisonExportError(_SOURCE_REFUSED)
    model_id, pipeline, embedding_dim = _model_identity(root)
    slices = _mapping(root.get("slices")) or {}
    clustering = _section(slices, "clustering")
    clustering_live = _live(clustering)
    # Historical reports never recorded a clustering method or metric. Do not infer one from other metadata.
    return {
        "artifact_id": artifact_id,
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "pipeline": pipeline,
        "model_id": model_id,
        "embedding_dim": embedding_dim,
        "counts": _numbers(_mapping(root.get("counts")), COUNT_FIELDS, ()),
        "detection": _numbers(_mapping(root.get("detection")), DETECTION_COUNTS, DETECTION_RATES),
        "unknown_rejection": _numbers(_section(slices, "unknown_rejection"), UNKNOWN_COUNTS, UNKNOWN_RATES),
        "clustering": {
            "algorithm": None,
            "metric": None,
            "parameters": {
                "d_cut": None if clustering_live is None else _nonnegative_or_none(clustering_live.get("d_cut"))
            },
            **_numbers(clustering, CLUSTER_COUNTS, CLUSTER_RATES),
        },
        "identification": {
            "headline": _numbers(
                _section(slices, "headline_identification"), IDENTIFICATION_COUNTS, IDENTIFICATION_RATES
            ),
            "full": _numbers(
                _section(slices, "full_corpus_identification"), IDENTIFICATION_COUNTS, IDENTIFICATION_RATES
            ),
        },
        "slice_sections": [name for name in SLICE_SECTIONS if _section(slices, name) is not None],
        "compatibility": "unknown",
        "qualification": "unqualified",
    }


# --- evidence reads: pointer API only, plus one bound read of the consumed bytes -------------------


def _identity(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_chunk(fd: int, size: int) -> bytes:
    return os.read(fd, size)


def _read_fd(fd: int, linked: os.stat_result) -> tuple[bytes, os.stat_result, os.stat_result]:
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode) or (before.st_dev, before.st_ino) != (linked.st_dev, linked.st_ino):
        raise ComparisonExportError(_SOURCE_CHANGED)
    if before.st_size > MAX_SOURCE_BYTES:
        raise ComparisonExportError(_SOURCE_TOO_LARGE)
    chunks: list[bytes] = []
    total = 0
    while total <= MAX_SOURCE_BYTES:
        chunk = _read_chunk(fd, min(READ_CHUNK, MAX_SOURCE_BYTES + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    if total > MAX_SOURCE_BYTES:
        raise ComparisonExportError(_SOURCE_TOO_LARGE)
    return b"".join(chunks), before, os.fstat(fd)


def _read_bound(path: str, expected_sha256: str) -> bytes:
    """One bounded read of a regular file. The bytes consumed must hash to the canonical file SHA-256."""
    try:
        linked = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        raise ComparisonExportError(_STATUS_MISSING) from None
    except OSError:
        raise ComparisonExportError(_SOURCE_UNREADABLE) from None
    if not stat.S_ISREG(linked.st_mode):
        raise ComparisonExportError(_SOURCE_NOT_REGULAR)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ComparisonExportError(_SOURCE_CHANGED) from None
        raise ComparisonExportError(_SOURCE_UNREADABLE) from None
    try:
        raw, before, after = _read_fd(fd, linked)
    except OSError:
        raise ComparisonExportError(_SOURCE_UNREADABLE) from None
    finally:
        os.close(fd)
    try:
        pathname = os.stat(path, follow_symlinks=False)
    except OSError:
        raise ComparisonExportError(_SOURCE_CHANGED) from None
    stable = _identity(before) == _identity(after) == _identity(pathname)
    if not stable or not stat.S_ISREG(pathname.st_mode) or len(raw) != before.st_size:
        raise ComparisonExportError(_SOURCE_CHANGED)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ComparisonExportError(_SOURCE_MISMATCH)
    return raw


def _pointer(evidence_db: Path, artifact_id: str) -> dict:
    pointer = firbench_evidence.show_artifact(evidence_db, artifact_id)
    if pointer["kind"] != POINTER_KIND:
        raise ComparisonExportError(_NOT_REPORT_POINTER)
    status = firbench_evidence.check_artifact(evidence_db, artifact_id)["status"]
    if status == "missing":
        raise ComparisonExportError(_STATUS_MISSING)
    if status != "matched":
        raise ComparisonExportError(_STATUS_CHANGED)
    return {field: pointer[field] for field in SOURCE_FIELDS}


def _report_for(evidence_db: Path, artifact_id: str, pointer: dict) -> dict:
    path = firbench_evidence.resolve_artifact(evidence_db, artifact_id)
    raw = _read_bound(path, pointer["file_sha256"])
    report = summarize_legacy_report(raw, artifact_id=artifact_id)
    report["qualification"] = pointer["qualification"]
    return report


def _requested_ids(artifact_ids: Sequence[str]) -> list[str]:
    if isinstance(artifact_ids, (str, bytes)) or not isinstance(artifact_ids, Sequence) or not artifact_ids:
        raise ComparisonExportError(_ID_LIST)
    if not all(isinstance(item, str) for item in artifact_ids):
        raise ComparisonExportError(_ID_LIST)
    ids = sorted(set(artifact_ids))
    if len(ids) > MAX_ARTIFACT_IDS:
        raise ComparisonExportError(_TOO_MANY_IDS)
    for artifact_id in ids:
        _check_artifact_id(artifact_id)
    return ids


def export_comparison(evidence_db: Path, artifact_ids: Sequence[str]) -> dict:
    """Build the export in memory. Nothing is written here; ``write_export`` publishes it."""
    ids = _requested_ids(artifact_ids)
    try:
        pointers = {artifact_id: _pointer(evidence_db, artifact_id) for artifact_id in ids}
        groups: dict[str, list[str]] = {}
        for artifact_id in ids:
            groups.setdefault(pointers[artifact_id]["file_sha256"], []).append(artifact_id)
        # One projection per unique canonical hash, keyed by its lowest artifact ID. Aliases stay in dedup.
        ordered = sorted(groups.items(), key=lambda item: item[1][0])
        reports = [_report_for(evidence_db, aliases[0], pointers[aliases[0]]) for _, aliases in ordered]
    except firbench_evidence.EvidenceError as exc:
        raise ComparisonExportError(str(exc)) from None
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "sources": [pointers[artifact_id] for artifact_id in ids],
        "dedup": [{"file_sha256": sha, "artifact_ids": aliases} for sha, aliases in ordered],
        "reports": reports,
    }


# --- payload validation and no-clobber publication -------------------------------------------------


def _check_sha(value: object, pattern: re.Pattern[str]) -> None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ComparisonExportError(_PAYLOAD_INVALID)


def _check_optional_sha(value: object, pattern: re.Pattern[str]) -> None:
    if value is not None:
        _check_sha(value, pattern)


def _check_numbers(section: object, counts: Sequence[str], rates: Sequence[str]) -> None:
    if not isinstance(section, dict) or set(section) != set(counts) | set(rates):
        raise ComparisonExportError(_PAYLOAD_INVALID)
    for name in counts:
        _count_or_none(section[name])
    for name in rates:
        _rate_or_none(section[name])


def _check_source(source: object) -> None:
    if not isinstance(source, dict) or set(source) != set(SOURCE_FIELDS):
        raise ComparisonExportError(_PAYLOAD_INVALID)
    _check_artifact_id(source["artifact_id"])
    _check_sha(source["file_sha256"], _SHA256_RE)
    _check_optional_sha(source["source_sha"], _SHA40_RE)
    _check_optional_sha(source["manifest_sha256"], _SHA256_RE)
    if source["kind"] != POINTER_KIND or source["qualification"] not in firbench_evidence.QUALIFICATIONS:
        raise ComparisonExportError(_PAYLOAD_INVALID)
    if source["manifest_hash_kind"] not in (None, *firbench_evidence.HASH_KINDS):
        raise ComparisonExportError(_PAYLOAD_INVALID)


def _check_report(report: object) -> None:
    if not isinstance(report, dict) or set(report) != set(REPORT_FIELDS):
        raise ComparisonExportError(_PAYLOAD_INVALID)
    _check_artifact_id(report["artifact_id"])
    _check_sha(report["file_sha256"], _SHA256_RE)
    if report["model_id"] not in (None, *MODEL_PIPELINES) or report["pipeline"] != MODEL_PIPELINES.get(
        report["model_id"]
    ):
        raise ComparisonExportError(_PAYLOAD_INVALID)
    _dimension_or_none(report["embedding_dim"])
    _check_numbers(report["counts"], COUNT_FIELDS, ())
    _check_numbers(report["detection"], DETECTION_COUNTS, DETECTION_RATES)
    _check_numbers(report["unknown_rejection"], UNKNOWN_COUNTS, UNKNOWN_RATES)
    clustering = report["clustering"]
    if (
        not isinstance(clustering, dict)
        or set(clustering) != set(CLUSTER_COUNTS) | set(CLUSTER_RATES) | {"algorithm", "metric", "parameters"}
        or clustering.get("algorithm") is not None
        or clustering.get("metric") is not None
    ):
        raise ComparisonExportError(_PAYLOAD_INVALID)
    parameters = clustering.get("parameters")
    if not isinstance(parameters, dict) or set(parameters) != {"d_cut"}:
        raise ComparisonExportError(_PAYLOAD_INVALID)
    _nonnegative_or_none(parameters["d_cut"])
    _check_numbers(
        {k: v for k, v in clustering.items() if k not in ("algorithm", "metric", "parameters")},
        CLUSTER_COUNTS,
        CLUSTER_RATES,
    )
    identification = report["identification"]
    if not isinstance(identification, dict) or set(identification) != {"headline", "full"}:
        raise ComparisonExportError(_PAYLOAD_INVALID)
    for section in ("headline", "full"):
        _check_numbers(identification[section], IDENTIFICATION_COUNTS, IDENTIFICATION_RATES)
    slice_sections = report["slice_sections"]
    if not isinstance(slice_sections, list) or any(name not in SLICE_SECTIONS for name in slice_sections):
        raise ComparisonExportError(_PAYLOAD_INVALID)
    if report["compatibility"] != "unknown" or report["qualification"] not in firbench_evidence.QUALIFICATIONS:
        raise ComparisonExportError(_PAYLOAD_INVALID)


def _serialize(payload: dict) -> bytes:
    """Validate and render the whole payload before any filesystem mutation."""
    try:
        if not isinstance(payload, dict) or set(payload) != {"schema", "schema_version", "sources", "dedup", "reports"}:
            raise ComparisonExportError(_PAYLOAD_INVALID)
        if payload["schema"] != SCHEMA or type(payload["schema_version"]) is not int:
            raise ComparisonExportError(_PAYLOAD_INVALID)
        if payload["schema_version"] != SCHEMA_VERSION:
            raise ComparisonExportError(_PAYLOAD_INVALID)
        if any(type(payload[field]) is not list for field in ("sources", "dedup", "reports")):
            raise ComparisonExportError(_PAYLOAD_INVALID)
        for source in payload["sources"]:
            _check_source(source)
        for group in payload["dedup"]:
            if not isinstance(group, dict) or set(group) != {"file_sha256", "artifact_ids"}:
                raise ComparisonExportError(_PAYLOAD_INVALID)
            _check_sha(group["file_sha256"], _SHA256_RE)
            if not isinstance(group["artifact_ids"], list) or not group["artifact_ids"]:
                raise ComparisonExportError(_PAYLOAD_INVALID)
            for artifact_id in group["artifact_ids"]:
                _check_artifact_id(artifact_id)
        for report in payload["reports"]:
            _check_report(report)
        text = json.dumps(payload, allow_nan=False, indent=2, sort_keys=True, ensure_ascii=True)
    except (KeyError, TypeError, ValueError, ComparisonExportError):
        raise ComparisonExportError(_PAYLOAD_INVALID) from None
    return (text + "\n").encode("ascii")


def write_export(payload: dict, out: Path) -> Path:
    """Publish with no-clobber semantics: write a private temporary, then hard-link it to the final name.

    ``os.link`` fails if the final name exists in any form, so a file, symlink, directory, or competing writer
    is never replaced. Only the temporary this call created is removed.
    """
    data = _serialize(payload)
    target = Path(out)
    temp = target.parent / f".{target.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(temp, flags, 0o600)
    except OSError:
        raise ComparisonExportError(_OUTPUT_UNWRITABLE) from None
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp, target)
    except FileExistsError:
        raise ComparisonExportError(_OUTPUT_EXISTS) from None
    except OSError:
        raise ComparisonExportError(_OUTPUT_UNWRITABLE) from None
    finally:
        with contextlib.suppress(OSError):
            os.unlink(temp)
    return target
