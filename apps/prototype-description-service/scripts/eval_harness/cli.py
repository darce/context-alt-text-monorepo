"""Eval-harness CLI: fetch / score / run / seed-roster / seed-scenes.

Split Phase: ``fetch`` walks the golden manifest against the remote OCI service
(concurrency 1) and writes a run record; ``score`` is pure and offline;
``run`` composes both. ``seed-roster`` is the one-time idempotent eval-tenant
setup. Live subcommands require ``ACX_EVAL_LIVE=1`` plus ``ACX_EVAL_BASE_URL``
and ``ACX_EVAL_API_KEY`` (the dedicated eval-tenant key — never the demo
tenant's) so unit tests and CI can never accidentally hit the service.

rg-007: one failing image never halts the run (per-item isolation), but
``stall_limit`` consecutive failures aborts with a non-zero exit.

LLM-judge tier: ``--llm-judge`` is accepted but is a stub (assessment §6c
tiers 3-4 are out of the MVP); it fails fast with a clear message.

Retention: run records/reports land in ``scripts/eval_harness/out/``
(git-ignored) and are pruned keep-last-N (default 10); the ignore-list file is
never pruned. Curated baselines are promoted to ``docs/tasks/vlm/`` by hand.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, NamedTuple

from scene.config.profiles import PROFILE_SPECS, DescriptionProfile
from scene.domain.description import DescriptionAdapterKind
from shared.secrets import get_secret_provider

from .face_bakeoff import (
    CANDIDATE_MODEL_ID,
    build_candidate_leg,
    build_occlusion_twin_pairs,
    build_pinned_cache_detector,
    walk_face_run_record,
)
from .face_bakeoff import (
    BoundedStallError as FaceBoundedStallError,
)
from .face_run_record import FaceRunRecordError, validate_face_run_record
from .manifest import GoldenManifest, ManifestError, _resolve_image, load_manifest
from .perf_leg import PerfLegError
from .remote_client import RemoteClientError, RemoteSceneClient
from .report import (
    WRONG_NAME_RATE_FLOOR,
    Audience,
    ReportError,
    build_face_reports,
    build_reports,
    occlusion_inputs_from_record,
    score_face_run_record,
    score_run_record,
)
from .schema import SCHEMA, DocKind
from .seed_roster import seed, seed_scenes

DEFAULT_KEEP = 10
DEFAULT_STALL_LIMIT = 5
OUT_DIR = Path(__file__).parent / "out"
IGNORE_LIST_NAME = "ignore-list.json"
_RUN_STAMP_RE = re.compile(r"^run-(\d{8}-\d{6})")


def _keep_arg(raw: str) -> int:
    """argparse type for ``--keep``: at least 1 so a run never prunes its own record (S3-07)."""
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


def _limit_arg(raw: str) -> int:
    """argparse type for ``--limit``: positive int; reject 0/negative (S8-03 / S6-02).

    ``limit=0`` is falsy and previously silently ran the full corpus; negative
    values silently sliced the tail off. Fail at parse time instead.
    """
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


def _provider_value(raw: str) -> str:
    """argparse type for ``--provider``: a registered hosted description profile (rg-008, sr-007)."""
    value = raw.strip()
    try:
        profile = DescriptionProfile(value)
    except ValueError:
        hosted = [p.value for p, s in PROFILE_SPECS.items() if s.adapter_kind is DescriptionAdapterKind.HOSTED_PROVIDER]
        raise argparse.ArgumentTypeError(f"{raw!r} is not a description profile; hosted profiles: {hosted}") from None
    if PROFILE_SPECS[profile].adapter_kind is not DescriptionAdapterKind.HOSTED_PROVIDER:
        raise argparse.ArgumentTypeError(f"{raw!r} is not a hosted profile (adapter_kind != hosted_provider)")
    return value


class BoundedStallError(RuntimeError):
    """Aborted after too many consecutive per-item failures (rg-007).

    Carries the partial run record (``aborted: true``) so an aborted run is
    still diagnosable — the per-item errors are the whole point of the abort.
    """

    def __init__(self, message: str, partial_record: dict[str, Any]) -> None:
        super().__init__(message)
        self.partial_record = partial_record


class MaxCostExceededError(RuntimeError):
    """Aborted before a paid provider call would push estimated spend past ``--max-cost`` (E20-11).

    Like ``BoundedStallError``, carries the partial record so the capped run is
    still scoreable evidence.
    """

    def __init__(self, message: str, partial_record: dict[str, Any]) -> None:
        super().__init__(message)
        self.partial_record = partial_record


class ProviderMismatchError(RuntimeError):
    """The service's describe response does not corroborate the claimed ``--provider`` (rg-015).

    The flag cannot switch the server profile (that is fixed by
    ``ACX_DESCRIPTION_ADAPTER`` on the service), so the harness verifies each
    item's ``provider_disclosure`` and aborts rather than stamping mislabeled
    benchmark evidence. Carries the partial record for diagnosis.
    """

    def __init__(self, message: str, partial_record: dict[str, Any]) -> None:
        super().__init__(message)
        self.partial_record = partial_record


def fetch_run_record(
    manifest: GoldenManifest,
    images_dir: str,
    client: Any,
    *,
    head_sha: str,
    limit: int | None = None,
    stall_limit: int = DEFAULT_STALL_LIMIT,
    started_at: str = "1970-01-01T00:00:00Z",
    provider: str | None = None,
    cost_per_image_usd: float | None = None,
    max_cost_usd: float | None = None,
    spent_usd: float = 0.0,
) -> dict[str, Any]:
    """Walk manifest entries sequentially; isolate per-item failures; bound stalls.

    E20-11: ``provider`` stamps the hosted description profile under test into the
    provenance and is *verified* against each item's ``provider_disclosure``
    (``ProviderMismatchError`` on drift — the flag cannot switch the server
    profile, so unverified stamping would fabricate evidence, rg-015).
    ``cost_per_image_usd`` (the provider's published per-request price) is billed
    per *attempted, non-cached* describe call — cache hits (``cached: true``) are
    refunded and analyze/identity calls are provider-free — yielding
    ``est_cost_usd``/``paid_describe_calls``; ``max_cost_usd`` aborts *before* the
    paid call that would push ``spent_usd`` + this run's estimate past the cap
    (``spent_usd`` carries spend from earlier legs of a matrix invocation).
    ``latency_s`` times the describe call only, not the recognition job polling.
    """
    images_root = Path(images_dir)
    if limit is not None and limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit}")
    entries = manifest.entries[:limit] if limit is not None else manifest.entries
    items: list[dict[str, Any]] = []
    consecutive_failures = 0
    paid_calls = 0
    expected_model_id: str | None = None
    if provider is not None:
        try:
            expected_model_id = PROFILE_SPECS[DescriptionProfile(provider)].model_id
        except ValueError:
            expected_model_id = None  # direct callers may pass labels outside the registry

    def _record(aborted: bool = False) -> dict[str, Any]:
        provenance: dict[str, Any] = {
            "manifest_sha256": _manifest_sha(manifest),
            "base_url": getattr(client, "base_url", "unknown"),
            "head_sha": head_sha,
            "started_at": started_at,
        }
        if provider is not None:
            provenance["provider"] = provider
        if cost_per_image_usd is not None:
            provenance["cost_per_image_usd"] = cost_per_image_usd
            provenance["paid_describe_calls"] = paid_calls
            provenance["est_cost_usd"] = round(cost_per_image_usd * paid_calls, 6)
        record: dict[str, Any] = {
            "schema": SCHEMA,
            "kind": DocKind.RUN_RECORD.value,
            "provenance": provenance,
            "items": items,
        }
        if aborted:
            record["aborted"] = True
        return record

    for entry in entries:
        if max_cost_usd is not None and cost_per_image_usd is not None:
            # Pre-call the cache state is unknown, so the projection is conservative:
            # the next describe is assumed paid.
            projected = spent_usd + cost_per_image_usd * (paid_calls + 1)
            if projected > max_cost_usd:
                raise MaxCostExceededError(
                    f"next paid call would raise estimated spend to ${projected:.4f} "
                    f"(> --max-cost ${max_cost_usd:.4f}); aborting before {entry.path}",
                    partial_record=_record(aborted=True),
                )
        # NFC/NFD-tolerant resolve (same as hash verify / seed_scenes) so a
        # Linux host whose fixture copy flipped normalization still reads bytes
        # after load_manifest(images_dir=...) passed (S6-03 / S7-01).
        image_path = _resolve_image(images_root, entry.path)
        item: dict[str, Any] = {
            "media_id": entry.media_id,
            "path": entry.path,
            "describe": None,
            "identities": [],
            "face_count": 0,
            "error": None,
            "latency_s": None,
            # A-08: absolute-pixel bboxes are only well-defined with image size.
            "image_width": None,
            "image_height": None,
            # A-07: "positional" | "degraded" once identities are extracted.
            "identity_ordering": None,
        }
        describe_started: float | None = None
        try:
            if image_path is None:
                raise FileNotFoundError(f"image file missing after NFC/NFD resolve: {entry.path}")
            image_bytes = image_path.read_bytes()
            width, height = _image_dimensions(image_bytes)
            item["image_width"] = width
            item["image_height"] = height
            describe_started = time.monotonic()
            # Billed on attempt (a failed call may still charge); refunded on cache hit.
            paid_calls += 1
            item["describe"] = client.describe(
                image_bytes=image_bytes,
                filename=image_path.name,
                media_id=entry.media_id,
                context_pack=entry.context_pack.model_dump(exclude_none=True),
            )
            item["latency_s"] = round(time.monotonic() - describe_started, 3)
            if isinstance(item["describe"], dict) and item["describe"].get("cached") is True:
                paid_calls -= 1
            job_id = client.analyze([(entry.media_id, image_path.name, image_bytes)])
            client.wait_job(job_id)
            identities_payload = client.media_identities([entry.media_id])
            identities, face_count, ordering_source = _extract_identities(
                identities_payload, entry.media_id
            )
            item["identities"] = identities
            item["face_count"] = face_count
            item["identity_ordering"] = ordering_source
        except Exception as exc:  # noqa: BLE001 — per-item isolation is the contract (rg-007)
            item["error"] = f"{type(exc).__name__}: {exc}"
            if item["latency_s"] is None and describe_started is not None:
                item["latency_s"] = round(time.monotonic() - describe_started, 3)
            consecutive_failures += 1
            if consecutive_failures >= stall_limit:
                items.append(item)
                raise BoundedStallError(
                    f"{consecutive_failures} consecutive item failures (last: {entry.path}); aborting run",
                    partial_record=_record(aborted=True),
                ) from exc
        else:
            consecutive_failures = 0
            if provider is not None:
                describe = item["describe"] if isinstance(item["describe"], dict) else {}
                disclosure = describe.get("provider_disclosure")
                response_model = describe.get("model_id")
                corroborated = (
                    isinstance(disclosure, dict)
                    and disclosure.get("provider") == "hosted"
                    and disclosure.get("left_service_boundary") is True
                    # Disambiguate WHICH hosted profile when both sides expose a model id.
                    and (response_model is None or expected_model_id is None or response_model == expected_model_id)
                )
                if not corroborated:
                    items.append(item)
                    raise ProviderMismatchError(
                        f"--provider {provider!r} claimed but {entry.path}'s describe response does not "
                        f"corroborate it (provider_disclosure={disclosure!r}, model_id={response_model!r}, "
                        f"expected model {expected_model_id!r}); the service profile is fixed server-side "
                        "by ACX_DESCRIPTION_ADAPTER — refusing to stamp mislabeled evidence",
                        partial_record=_record(aborted=True),
                    )
        items.append(item)

    return _record()


def _parse_identity_bbox(raw: Any) -> dict[str, int | float] | None:
    """Validate wire bbox {x, y, width, height}; never invent or accept w/h aliases (rg-015)."""
    if not isinstance(raw, dict):
        return None
    try:
        x, y, width, height = raw["x"], raw["y"], raw["width"], raw["height"]
    except KeyError:
        return None
    if not all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in (x, y, width, height)
    ):
        return None
    return {"x": x, "y": y, "width": width, "height": height}


def _image_dimensions(image_bytes: bytes) -> tuple[int | None, int | None]:
    """Read (width, height) from image bytes; (None, None) when undecodable (A-08)."""
    try:
        from PIL import Image

        with Image.open(BytesIO(image_bytes)) as im:
            width, height = im.size
        return int(width), int(height)
    except Exception:  # noqa: BLE001 — non-image fixtures in unit tests; stamp None
        return None, None


def identity_names(identities: object) -> list[str]:
    """Turn stored ``identities`` into an ordered list of name strings.

    Greenfield (A-06): only the positional dict row shape from
    ``_extract_identities`` is accepted — ``{"name", "bbox", "unpositioned", ...}``.
    Bare-string lists raise; dual-shape shims are forbidden. Left-to-right order
    is preserved — never re-sorted alphabetically. Dict entries with a missing or
    empty ``name`` raise rather than being silently skipped.
    """
    if not isinstance(identities, list):
        raise TypeError(
            f"identities must be a list of dict rows, got {type(identities).__name__}"
        )
    names: list[str] = []
    for index, entry in enumerate(identities):
        if not isinstance(entry, dict):
            raise TypeError(
                f"identities[{index}] must be a dict identity row; got "
                f"{type(entry).__name__} — greenfield rejects bare-string identity lists"
            )
        name = entry.get("name")
        if not name:
            raise ValueError(
                f"identities[{index}] has empty/missing 'name' "
                f"(keys present: {sorted(entry)!r})"
            )
        names.append(str(name))
    return names


def _identity_row_from_wire(row: dict[str, Any], *, name: str, bbox: dict[str, int | float] | None) -> dict[str, Any]:
    """Build a stored identity row, preserving wire ``identity_id`` when present (A-09)."""
    stored: dict[str, Any] = {
        "name": name,
        "bbox": bbox,
        "unpositioned": bbox is None,
    }
    if "identity_id" in row:
        stored["identity_id"] = row["identity_id"]
    return stored


def _extract_identities(payload: Any, media_id: int) -> tuple[list[dict[str, Any]], int, str]:
    """Normalize /media/identities rows for one media_id -> (identities, face_count, ordering).

    Wire shape (MediaIdentityService.list_by_media_ids): each row carries
    ``cluster_label`` and ``is_auto_label`` (inverted ``user_confirmed``). There
    is no ``user_confirmed`` key on this route — filter confirmed labels via
    ``is_auto_label is not True`` (S8-01 / rg-005).

    Confirmed names are bound to faces by left-to-right bbox position (ascending x,
    then y, then name). Each entry carries its bbox and the wire ``identity_id``
    when present (A-09). Rows with missing/malformed bbox are kept, marked
    unpositioned, and sorted after positioned rows — never dropped and never given
    a fabricated bbox (rg-015). When any confirmed row is unpositioned the
    ordering_source is ``\"degraded\"`` so callers/report can surface the fall-back
    rather than silently reinstating alphabetical order (A-07).
    """
    if not isinstance(payload, list):
        raise RemoteClientError(
            f"media_identities returned {type(payload).__name__}, expected a list of "
            "identity rows (rg-015) — per-item isolation records this as an item error"
        )
    positioned: list[tuple[int | float, int | float, str, dict[str, Any]]] = []
    unpositioned: list[tuple[str, dict[str, Any]]] = []
    face_count = 0
    for row in payload:
        if not isinstance(row, dict) or int(row.get("media_id", -1)) != media_id:
            continue
        face_count += 1
        label = row.get("cluster_label") or row.get("label") or row.get("name")
        # Confirmed labels only: is_auto_label True => auto-propagated, skip.
        # Missing key treated as confirmed (legacy/test fixtures without the field).
        if not label or row.get("is_auto_label") is True:
            continue
        name = str(label)
        bbox = _parse_identity_bbox(row.get("bbox"))
        stored = _identity_row_from_wire(row, name=name, bbox=bbox)
        if bbox is None:
            unpositioned.append((name, stored))
        else:
            positioned.append((bbox["x"], bbox["y"], name, stored))
    positioned.sort(key=lambda t: (t[0], t[1], t[2]))
    # Unpositioned rows keep a stable secondary order (name) but the overall
    # ordering_source is degraded so report surfaces the loss of pure L→R.
    unpositioned.sort(key=lambda t: t[0])
    identities = [t[-1] for t in positioned] + [t[1] for t in unpositioned]
    ordering_source = "degraded" if unpositioned else "positional"
    return identities, face_count, ordering_source


def _manifest_sha(manifest: GoldenManifest) -> str:
    canonical = json.dumps(manifest.model_dump(), sort_keys=True).encode()
    return hashlib.sha256(canonical).hexdigest()


def prune_out_dir(out_dir: str, *, keep: int = DEFAULT_KEEP) -> list[str]:
    """Keep the newest ``keep`` runs; delete each stale run's record + reports together.

    Group every ``run-<stamp>*`` file (record, ``-report.json``, ``-report.md``,
    ``-aborted.json``) by its timestamp and prune whole stale runs, so markdown
    reports no longer accumulate unbounded and a report is never deleted while its
    record survives (S3-02). ``keep`` must be >= 1 so a run flow can never delete
    the record it just wrote (S3-07); the ignore list is never touched.
    """
    if keep < 1:
        raise ValueError(f"keep must be >= 1, got {keep}")
    root = Path(out_dir)
    groups: dict[str, list[Path]] = {}
    for path in root.glob("run-*"):
        if path.name == IGNORE_LIST_NAME:
            continue
        match = _RUN_STAMP_RE.match(path.name)
        if match:
            groups.setdefault(match.group(1), []).append(path)
    removed: list[str] = []
    for stamp in sorted(groups)[:-keep]:
        for path in groups[stamp]:
            path.unlink()
            removed.append(path.name)
    return removed


def _require_live_env() -> tuple[str, str, str]:
    if os.environ.get("ACX_EVAL_LIVE") != "1":
        sys.exit("live subcommand requires ACX_EVAL_LIVE=1 (safety gate; see README)")
    base_url = os.environ.get("ACX_EVAL_BASE_URL", "")
    api_key = get_secret_provider().get_secret_optional("ACX_EVAL_API_KEY", "") or ""
    tenant_id = os.environ.get("ACX_EVAL_TENANT_ID", "")
    if not base_url or not api_key or not tenant_id:
        sys.exit(
            "ACX_EVAL_BASE_URL, ACX_EVAL_API_KEY, and ACX_EVAL_TENANT_ID are required — "
            "use the dedicated eval tenant, never the demo tenant"
        )
    return base_url, api_key, tenant_id


def _head_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _images_dir() -> str:
    images_dir = os.environ.get("GOLDEN_IMAGES_DIR", "")
    if not images_dir:
        sys.exit("GOLDEN_IMAGES_DIR is not set — see scene/tests/seed/README.md for the rsync bootstrap")
    return images_dir


def _load_ignore_list(source_dir: Path) -> dict[str, Any] | None:
    """Load ``ignore-list.json`` from beside the run record being scored.

    Reading it from the record's own directory (not always ``OUT_DIR``) removes an
    ambient input that silently changed a committed baseline's re-score depending
    on the machine's ``out/`` contents (S3-05c). Structure is validated fail-fast:
    a malformed ``wrong_names`` value can no longer no-op silently (S3-05a, rg-008).

    Known limitation (S3-05b): ignored pairs are keyed on (path, name) with no
    expiry/commit binding, so a pair triaged once stays suppressed even if the
    same wrong-name later genuinely regresses. Every suppressed pair is still
    surfaced under ``ignored_wrong_names`` in the report so it is never invisible.
    """
    path = source_dir / IGNORE_LIST_NAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ManifestError(f"{path} must contain a JSON object")
    wrong = payload.get("wrong_names", [])
    if not isinstance(wrong, list) or not all(
        isinstance(pair, list) and len(pair) == 2 and all(isinstance(part, str) for part in pair) for pair in wrong
    ):
        raise ManifestError(f"{path}: 'wrong_names' must be a list of [path, name] string pairs")
    return payload


def _reject_llm_judge(args: argparse.Namespace) -> None:
    """Reject the stub LLM-judge tier before any live work (§6c tiers 3-4 out of MVP).

    Checked at the top of fetch/run/score so ``run --llm-judge`` and
    ``fetch --llm-judge`` fail fast instead of burning 38 remote calls first (S3-06).
    """
    if getattr(args, "llm_judge", False):
        sys.exit("--llm-judge is a stub: the LLM-judge tier is not implemented in this MVP (§6c)")


def _cmd_fetch(args: argparse.Namespace) -> list[str]:
    """Fetch one run record per ``--provider`` value (or a single unstamped run)."""
    _reject_llm_judge(args)
    base_url, api_key, tenant_id = _require_live_env()
    images_dir = _images_dir()
    manifest = load_manifest(args.manifest, images_dir=images_dir)
    # Dedupe (order-preserving): a repeated matrix value would overwrite its own
    # same-second record path and double-spend for identical evidence.
    providers: list[str | None] = list(dict.fromkeys(args.provider)) if args.provider else [None]
    OUT_DIR.mkdir(exist_ok=True)
    record_paths: list[str] = []
    spent_usd = 0.0
    for provider in providers:
        client = RemoteSceneClient(base_url=base_url, api_key=api_key, tenant_id=tenant_id)
        started_at = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        stamp = started_at.replace(":", "").replace("-", "").replace("T", "-").rstrip("Z")
        suffix = f"-{provider}" if provider else ""
        record_path = OUT_DIR / f"run-{stamp}{suffix}.json"
        try:
            record = fetch_run_record(
                manifest,
                images_dir,
                client,
                head_sha=_head_sha(),
                limit=args.limit,
                stall_limit=args.stall_limit,
                started_at=started_at,
                provider=provider,
                cost_per_image_usd=args.cost_per_image,
                max_cost_usd=args.max_cost,
                spent_usd=spent_usd,
            )
        except (BoundedStallError, MaxCostExceededError, ProviderMismatchError) as exc:
            aborted_path = OUT_DIR / f"run-{stamp}{suffix}-aborted.json"
            aborted_path.write_text(json.dumps(exc.partial_record, indent=2, sort_keys=True) + "\n")
            sys.exit(f"{type(exc).__name__}: {exc} — partial record saved to {aborted_path}")
        finally:
            client.close()
        if args.cost_per_image is not None:
            # --max-cost caps the whole invocation, not each matrix leg; est_cost_usd
            # already excludes cache hits and never-issued calls.
            spent_usd += record["provenance"].get("est_cost_usd", 0.0)
        record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        record_paths.append(str(record_path))
        print(record_path)
    # Never prune records this invocation just wrote (S3-07 across the matrix).
    prune_out_dir(str(OUT_DIR), keep=max(args.keep, len(record_paths)))
    return record_paths


def _check_score_determinism_cross_process(
    record_path: Path,
    manifest_path: str,
) -> None:
    """Re-run caption score in a FRESH process under varied PYTHONHASHSEED (§G).

    Mirrors ``_check_face_determinism_cross_process`` for the caption/report path.
    Baseline is computed in-process from the persisted run-record; each subprocess
    re-loads that same path from disk (not an in-memory twin of the first call) so
    hash-ordering, import-order, and mutated-anchor failures are visible.
    """
    # Baseline: current process, reading the persisted anchor.
    record = json.loads(record_path.read_text())
    manifest = load_manifest(manifest_path)
    entries = [e.model_dump() for e in manifest.entries]
    manifest_sha = _manifest_sha(manifest)
    ignore_list = _load_ignore_list(record_path.parent)
    roster = sorted(set(getattr(manifest, "roster", []) or []))
    base_json, base_md = build_reports(
        record,
        entries,
        ignore_list=ignore_list,
        score_manifest_sha256=manifest_sha,
        manifest_roster=roster,
    )

    script = (
        "import json,sys; "
        "from pathlib import Path; "
        "from scripts.eval_harness.manifest import load_manifest; "
        "from scripts.eval_harness.cli import _manifest_sha, _load_ignore_list; "
        "from scripts.eval_harness.report import build_reports; "
        "rec_path=Path(sys.argv[1]); "
        "rec=json.loads(rec_path.read_text()); "
        "man=load_manifest(sys.argv[2]); "
        "entries=[e.model_dump() for e in man.entries]; "
        "sha=_manifest_sha(man); "
        "ignore=_load_ignore_list(rec_path.parent); "
        "roster=sorted(set(getattr(man,'roster',None) or [])); "
        "j,m=build_reports(rec,entries,ignore_list=ignore,"
        "score_manifest_sha256=sha,manifest_roster=roster); "
        "sys.stdout.write(j); sys.stdout.write('---MD---'); sys.stdout.write(m)"
    )
    for hash_seed in ("0", "1", "42"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = hash_seed
        proc = subprocess.run(
            [sys.executable, "-c", script, str(record_path), manifest_path],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(Path.cwd()),
        )
        if proc.returncode != 0:
            sys.exit(
                f"determinism check FAILED: subprocess seed={hash_seed} rc={proc.returncode}: {proc.stderr}"
            )
        out = proc.stdout
        if "---MD---" not in out:
            sys.exit(f"determinism check FAILED: malformed subprocess output seed={hash_seed}")
        sub_json, sub_md = out.split("---MD---", 1)
        if sub_json != base_json or sub_md != base_md:
            sys.exit(
                f"determinism check FAILED: cross-process re-score differs under PYTHONHASHSEED={hash_seed}"
            )
    print("determinism check passed: cross-process re-score is bit-identical under varied PYTHONHASHSEED")


def _cmd_score(args: argparse.Namespace) -> None:
    _reject_llm_judge(args)
    record_path = Path(args.run_record)
    record = json.loads(record_path.read_text())
    manifest = load_manifest(args.manifest)
    entries = [e.model_dump() for e in manifest.entries]
    # Stamp the report with the manifest actually scored against, and verify it
    # against the run record's fetch-time sha instead of copying it blind (S3-04).
    manifest_sha = _manifest_sha(manifest)
    ignore_list = _load_ignore_list(record_path.parent)
    roster = sorted(set(getattr(manifest, "roster", []) or []))
    json_doc, md_doc = build_reports(
        record, entries, ignore_list=ignore_list, score_manifest_sha256=manifest_sha, manifest_roster=roster
    )
    if args.check_determinism:
        # VLM-6 S2A item 3: cross-process re-score from the persisted anchor under
        # varied PYTHONHASHSEED (same shape as score-face). Same-process double
        # build_reports only caught intra-call nondeterminism and certified nothing.
        _check_score_determinism_cross_process(record_path, args.manifest)
    base = record_path.with_suffix("")
    json_path, md_path = Path(f"{base}-report.json"), Path(f"{base}-report.md")
    json_path.write_text(json_doc)
    md_path.write_text(md_doc)
    # VLM-6 S5 W1 (VLM6-C-01 / VLM6-F-03): audience-aware export. Additive — the
    # full LOCAL report above is always written (operator triage + the failure gate
    # below score the whole corpus); --audience public ALSO emits a redacted,
    # publishable-only artifact. This is the sole sanctioned eval->public path,
    # the prerequisite that makes the rd.altcontext.com gallery (RND-1) safe.
    if getattr(args, "audience", Audience.LOCAL.value) == Audience.PUBLIC.value:
        public_json, public_md = build_reports(
            record,
            entries,
            ignore_list=ignore_list,
            score_manifest_sha256=manifest_sha,
            manifest_roster=roster,
            audience=Audience.PUBLIC,
        )
        public_json_path, public_md_path = Path(f"{base}-report.public.json"), Path(f"{base}-report.public.md")
        public_json_path.write_text(public_json)
        public_md_path.write_text(public_md)
        print(public_md_path)
    scored = score_run_record(
        record, entries, ignore_list=ignore_list, score_manifest_sha256=manifest_sha, manifest_roster=roster
    )
    print(md_path)
    verdict = scored.get("verdict") or {}
    print(
        f"scored={scored['counts']['scored']}/{scored['counts']['total']} "
        f"insertion_rate={scored['caption']['insertion_rate']} "
        f"wrong_names={len(scored['faces']['identification']['wrong_names'])} "
        f"verdict={verdict.get('verdict', 'unknown')} "
        f"wrong_name_rate={verdict.get('wrong_name_rate')} "
        f"wrong_name_rate_floor={verdict.get('wrong_name_rate_floor', WRONG_NAME_RATE_FLOOR)}"
    )
    # Fail loud when any item was skipped from scoring (S7-01): a "passing" run
    # that dropped NFC-miss / remote errors must not look like full-corpus evidence.
    # Gate name is distinct from the wrong-name floor gate below so a red run
    # says which one fired (VLM-6 S2A).
    failed = int(scored["counts"]["failed"])
    if failed > 0:
        sys.exit(
            f"score failed-items gate: {failed} item(s) not scored (see failures[] in {json_path}); "
            "refusing to treat a partial corpus as full eval evidence"
        )
    # VLM-6 S2A: wrong-name floor — hallucinated human names on photographs are
    # the highest-severity failure this harness detects; gate, do not merely report.
    wrong_name_rate = float(verdict.get("wrong_name_rate", 0.0))
    floor = float(verdict.get("wrong_name_rate_floor", WRONG_NAME_RATE_FLOOR))
    if wrong_name_rate > floor:
        sys.exit(
            f"score wrong-name floor gate: wrong_name_rate={wrong_name_rate} exceeds "
            f"floor={floor} (see {json_path})"
        )


def _cmd_run(args: argparse.Namespace) -> None:
    for record_path in _cmd_fetch(args):
        args.run_record = record_path
        _cmd_score(args)


def _cmd_seed_roster(args: argparse.Namespace) -> None:
    base_url, api_key, tenant_id = _require_live_env()
    client = RemoteSceneClient(base_url=base_url, api_key=api_key, tenant_id=tenant_id)
    try:
        summary = seed(args.entities, client, tenant_id=tenant_id)
    finally:
        client.close()
    print(json.dumps(summary.__dict__, indent=2, sort_keys=True))
    if summary.unlabeled_roster_names:
        sys.exit(f"seeding incomplete: unlabeled roster names {summary.unlabeled_roster_names}")


def _cmd_seed_scenes(args: argparse.Namespace) -> None:
    base_url, api_key, tenant_id = _require_live_env()
    images_dir = _images_dir()
    client = RemoteSceneClient(base_url=base_url, api_key=api_key, tenant_id=tenant_id)
    try:
        summary = seed_scenes(args.manifest, images_dir, client)
    finally:
        client.close()
    print(json.dumps(summary.__dict__, indent=2, sort_keys=True))
    if summary.unverified_media_ids:
        sys.exit(f"seeding incomplete: no identity rows detected for media_ids {summary.unverified_media_ids}")



class _FaceLegBundle(NamedTuple):
    """One bake-off leg wired for the walker + twin pass (leg-parameterized provenance)."""

    detector: Any
    aligner: Any
    embedder: Any
    model_id: str
    leg_mode: str | None
    # Non-candidate legs pin the twin landmark cache to the candidate-family
    # YuNet (EXP-08); None → the leg detector doubles as the cache detector.
    cache_detector: Any | None


_EVAL_BENCH_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _build_buffalo_leg() -> _FaceLegBundle:
    """Preflight + construct the fused buffalo_l baseline leg (FIR-1 head-to-head).

    PROV-01: buffalo run-records hold 512D embeddings of private images — they
    stay in git-ignored ``out/``; only score reports are promoted to
    ``docs/tasks/vlm/bakeoff-results/``.
    """
    if os.environ.get("ACX_EVAL_BENCH", "").strip().lower() not in _EVAL_BENCH_TRUTHY:
        sys.exit(
            "face-bakeoff --leg buffalo requires ACX_EVAL_BENCH=1 (SC-1: the buffalo_l "
            "incumbent is an eval-only reference leg). Set ACX_EVAL_BENCH=1 and install "
            "the [bench] extra first: uv sync --extra bench"
        )
    if importlib.util.find_spec("insightface") is None:
        sys.exit(
            "face-bakeoff --leg buffalo: insightface is not installed. Install the "
            "[bench] extra (uv sync --extra bench) and keep ACX_EVAL_BENCH=1. Model "
            "weights resolve via INSIGHTFACE_CACHE_DIR / INSIGHTFACE_HOME (root dir "
            "containing models/buffalo_l/), else ~/.insightface"
        )
    from .buffalo_bench import BUFFALO_LEG_MODE, BUFFALO_MODEL_ID, build_baseline_leg

    detector, aligner, embedder = build_baseline_leg()
    return _FaceLegBundle(
        detector=detector,
        aligner=aligner,
        embedder=embedder,
        model_id=BUFFALO_MODEL_ID,
        leg_mode=BUFFALO_LEG_MODE,
        cache_detector=build_pinned_cache_detector(),
    )


def _build_face_leg(leg: str) -> _FaceLegBundle:
    if leg == "buffalo":
        return _build_buffalo_leg()
    detector, aligner, embedder = build_candidate_leg()
    return _FaceLegBundle(
        detector=detector,
        aligner=aligner,
        embedder=embedder,
        model_id=CANDIDATE_MODEL_ID,
        leg_mode=None,
        cache_detector=None,
    )


def _cmd_face_bakeoff(args: argparse.Namespace) -> None:
    """Offline leg walk → face_run_record JSON in out/ (no tenant writes)."""
    # Leg preflight first: --leg buffalo failures (env flag / [bench] extra) must
    # surface before unrelated GOLDEN_IMAGES_DIR / manifest errors.
    leg = _build_face_leg(args.leg)
    images_dir = _images_dir()
    manifest = load_manifest(args.manifest)
    detector, aligner, embedder = leg.detector, leg.aligner, leg.embedder
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    try:
        record = walk_face_run_record(
            manifest,
            images_dir,
            detector=detector,
            embedder=embedder,
            aligner=aligner,
            model_id=leg.model_id,
            head_sha=_head_sha(),
            limit=args.limit,
            stall_limit=args.stall_limit,
            started_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            # rg-015: dim comes from the leg's embedder (the producer), so an
            # injected leg with a different space cannot mislabel the record.
            embedding_dim=getattr(embedder, "embedding_dim", None),
            leg=args.leg,
            leg_mode=leg.leg_mode,
        )
    except FaceBoundedStallError as exc:
        record = exc.partial_record
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / f"face-run-{stamp}-aborted.json"
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        prune_out_dir(str(OUT_DIR), keep=args.keep)
        print(path)
        sys.exit(f"FaceBoundedStallError: {exc}")
    # FIR5GL-01: synthetic occlusion twin pass — generate/render twins from the
    # frozen landmark cache, re-detect+embed the occluded pixels with the SAME
    # leg, and stamp document-level pair inputs (never items — EVAL-16 firewall).
    twin_pairs, twin_prov = build_occlusion_twin_pairs(
        manifest,
        images_dir,
        detector=detector,
        embedder=embedder,
        aligner=aligner,
        limit=args.limit,
        # EXP-08: non-candidate legs keep the twin universe pinned to the
        # candidate-family YuNet cache (None → leg detector, candidate case).
        cache_detector=leg.cache_detector,
    )
    record["provenance"]["occlusion_twin_pass"] = twin_prov
    if twin_pairs:
        record["occlusion_twin_pairs_by_tag"] = twin_pairs
    record = validate_face_run_record(record)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"face-run-{stamp}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    prune_out_dir(str(OUT_DIR), keep=args.keep)
    print(path)
    print(
        f"face-bakeoff items={len(record['items'])} "
        f"leg={record['provenance'].get('leg')} "
        f"model_id={record['provenance'].get('model_id')} "
        f"occlusion_twin_pairs={twin_prov['n_pairs']} "
        f"twin_errors={len(twin_prov['errors'])}"
    )


def _face_score_once(
    record: dict[str, Any],
    manifest: GoldenManifest,
    *,
    score_manifest_sha256: str,
    public: bool,
) -> tuple[str, str]:
    # FIR5GL-01: twins ride the record; real pairs derive from tagged entries.
    synth_pairs, real_pairs = occlusion_inputs_from_record(record, manifest)
    return build_face_reports(
        record,
        manifest,
        score_manifest_sha256=score_manifest_sha256,
        occlusion_pairs_by_tag=synth_pairs,
        real_occlusion_pairs_by_tag=real_pairs,
        public=public,
    )


def _check_face_determinism_cross_process(
    record_path: Path,
    manifest_path: str,
    *,
    public: bool,
) -> None:
    """Re-run score-face in a FRESH process under varied PYTHONHASHSEED (§G)."""
    # Baseline: current process
    record = json.loads(record_path.read_text())
    manifest = load_manifest(manifest_path)
    manifest_sha = _manifest_sha(manifest)
    base_json, base_md = _face_score_once(
        record, manifest, score_manifest_sha256=manifest_sha, public=public
    )

    script = (
        "import json,sys; "
        "from scripts.eval_harness.manifest import load_manifest; "
        "from scripts.eval_harness.cli import _manifest_sha; "
        "from scripts.eval_harness.report import build_face_reports, occlusion_inputs_from_record; "
        "rec=json.loads(open(sys.argv[1]).read()); "
        "man=load_manifest(sys.argv[2]); "
        "pub=sys.argv[3]=='1'; "
        "sp,rp=occlusion_inputs_from_record(rec,man); "
        "j,m=build_face_reports(rec,man,score_manifest_sha256=_manifest_sha(man),"
        "occlusion_pairs_by_tag=sp,real_occlusion_pairs_by_tag=rp,public=pub); "
        "sys.stdout.write(j); sys.stdout.write('---MD---'); sys.stdout.write(m)"
    )
    for hash_seed in ("0", "1", "42"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = hash_seed
        proc = subprocess.run(
            [sys.executable, "-c", script, str(record_path), manifest_path, "1" if public else "0"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(Path.cwd()),
        )
        if proc.returncode != 0:
            sys.exit(
                f"determinism check FAILED: subprocess seed={hash_seed} rc={proc.returncode}: {proc.stderr}"
            )
        out = proc.stdout
        if "---MD---" not in out:
            sys.exit(f"determinism check FAILED: malformed subprocess output seed={hash_seed}")
        sub_json, sub_md = out.split("---MD---", 1)
        if sub_json != base_json or sub_md != base_md:
            sys.exit(
                f"determinism check FAILED: cross-process re-score differs under PYTHONHASHSEED={hash_seed}"
            )
    print("determinism check passed: cross-process re-score is bit-identical under varied PYTHONHASHSEED")


def _cmd_score_face(args: argparse.Namespace) -> None:
    """Pure offline face score over the full unfiltered corpus (§G)."""
    record_path = Path(args.run_record)
    record = json.loads(record_path.read_text())
    if record.get("kind") == DocKind.FACE_RUN_RECORD.value:
        validate_face_run_record(record)
    manifest = load_manifest(args.manifest)
    manifest_sha = _manifest_sha(manifest)
    public = bool(getattr(args, "public", False))
    json_doc, md_doc = _face_score_once(
        record, manifest, score_manifest_sha256=manifest_sha, public=public
    )
    if args.check_determinism:
        _check_face_determinism_cross_process(record_path, args.manifest, public=public)
    base = record_path.with_suffix("")
    json_path, md_path = Path(f"{base}-face-report.json"), Path(f"{base}-face-report.md")
    json_path.write_text(json_doc)
    md_path.write_text(md_doc)
    synth_pairs, real_pairs = occlusion_inputs_from_record(record, manifest)
    scored = score_face_run_record(
        record,
        manifest,
        score_manifest_sha256=manifest_sha,
        occlusion_pairs_by_tag=synth_pairs,
        real_occlusion_pairs_by_tag=real_pairs,
    )
    occlusion_eligible = sum(
        int((block.get("synthetic") or {}).get("n_eligible") or 0)
        for block in (scored["slices"].get("occlusion") or {}).values()
        if isinstance(block, dict)
    )
    print(md_path)
    print(
        f"scored={scored['counts']['scored']}/{scored['counts']['total']} "
        f"matched_faces={scored['counts']['matched_faces']} "
        f"occlusion_n_eligible={occlusion_eligible} "
        f"directional_excluded={len(scored['gate_proposal']['excluded_directional'])}"
    )
    failed = int(scored["counts"]["failed"])
    if failed > 0:
        sys.exit(
            f"score-face gate failed: {failed} item(s) not scored (see failures[] in {json_path})"
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="eval_harness", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def _common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--manifest", default="scene/tests/seed/golden.json")
        p.add_argument("--limit", type=_limit_arg, default=None, help="cap images (must be >= 1)")
        p.add_argument("--stall-limit", type=int, default=DEFAULT_STALL_LIMIT)
        p.add_argument("--keep", type=_keep_arg, default=DEFAULT_KEEP)
        p.add_argument("--llm-judge", action="store_true", help="stub — not implemented (§6c)")
        p.add_argument("--check-determinism", action="store_true")

    def _audience_flag(p: argparse.ArgumentParser) -> None:
        # score/run only. LOCAL (default) writes the full operator report unchanged;
        # PUBLIC additionally emits a redacted publishable-only public artifact.
        p.add_argument(
            "--audience",
            choices=(Audience.LOCAL.value, Audience.PUBLIC.value),
            default=Audience.LOCAL.value,
            help=(
                "local (default) writes the full operator report; public ALSO emits a "
                "redacted publishable-only <run>-report.public.{json,md} (the only sanctioned "
                "eval->public path)"
            ),
        )

    def _provider_flags(p: argparse.ArgumentParser) -> None:
        # fetch/run only — score is pure/offline and must not accept paid-run flags.
        p.add_argument(
            "--provider",
            action="append",
            type=_provider_value,
            default=None,
            help=(
                "hosted description profile the target service is serving; verified against each "
                "response's provider_disclosure. Repeatable, but the server profile is fixed per "
                "deployment — each matrix leg needs the service reconfigured between invocations"
            ),
        )
        p.add_argument(
            "--cost-per-image",
            type=float,
            default=None,
            help="provider's published per-request price (USD); stamps est_cost_usd into provenance",
        )
        p.add_argument(
            "--max-cost",
            type=float,
            default=None,
            help="whole-invocation cap: abort before any paid call that would push estimated spend (USD) past it",
        )

    fetch_p = sub.add_parser("fetch", help="manifest -> remote calls -> run record")
    _common(fetch_p)
    _provider_flags(fetch_p)
    fetch_p.set_defaults(func=_cmd_fetch)

    score_p = sub.add_parser("score", help="run record -> reports (pure, offline)")
    _common(score_p)
    _audience_flag(score_p)
    score_p.add_argument("--run-record", required=True)
    score_p.set_defaults(func=_cmd_score)

    run_p = sub.add_parser("run", help="fetch then score")
    _common(run_p)
    _provider_flags(run_p)
    _audience_flag(run_p)
    run_p.set_defaults(func=_cmd_run)

    seed_p = sub.add_parser("seed-roster", help="idempotent eval-tenant roster seeding")
    seed_p.add_argument("--entities", required=True, help="<GOLDEN_IMAGES_DIR>/mock_entities")
    seed_p.set_defaults(func=_cmd_seed_roster)

    scenes_p = sub.add_parser("seed-scenes", help="idempotent eval-tenant scene-image seeding (E19-4a bboxes)")
    scenes_p.add_argument("--manifest", default="scene/tests/seed/golden.json")
    scenes_p.set_defaults(func=_cmd_seed_scenes)

    face_bo = sub.add_parser(
        "face-bakeoff",
        help="offline face walk (detect→align→embed) → face_run_record (FIR-5; no tenant writes)",
    )
    face_bo.add_argument("--manifest", default="scene/tests/seed/golden.json")
    face_bo.add_argument("--limit", type=_limit_arg, default=None)
    face_bo.add_argument("--stall-limit", type=int, default=DEFAULT_STALL_LIMIT)
    face_bo.add_argument("--keep", type=_keep_arg, default=DEFAULT_KEEP)
    face_bo.add_argument(
        "--leg",
        choices=("candidate", "buffalo"),
        default="candidate",
        help=(
            "face leg (candidate=YuNet+SFace; buffalo=InsightFace buffalo_l fused baseline — "
            "requires ACX_EVAL_BENCH=1 + the [bench] extra; PROV-01: buffalo run-records hold "
            "512D embeddings of private images and stay in git-ignored out/)"
        ),
    )
    face_bo.set_defaults(func=_cmd_face_bakeoff)

    score_face_p = sub.add_parser(
        "score-face",
        help="face run-record → face report (pure, offline; full unfiltered corpus)",
    )
    score_face_p.add_argument("--manifest", default="scene/tests/seed/golden.json")
    score_face_p.add_argument("--run-record", required=True)
    score_face_p.add_argument(
        "--check-determinism",
        action="store_true",
        help="re-score in a fresh process under varied PYTHONHASHSEED; bit-identical JSON/MD required",
    )
    score_face_p.add_argument(
        "--public",
        action="store_true",
        help="post-score redact via redact_face_report_for_public (never pre-score drop)",
    )
    score_face_p.set_defaults(func=_cmd_score_face)


    args = parser.parse_args(argv)
    if getattr(args, "max_cost", None) is not None and getattr(args, "cost_per_image", None) is None:
        parser.error("--max-cost requires --cost-per-image (the cap is estimated spend; without a price it is a no-op)")
    try:
        args.func(args)
    except (
        ManifestError,
        RemoteClientError,
        BoundedStallError,
        FaceBoundedStallError,
        MaxCostExceededError,
        ProviderMismatchError,
        ReportError,
        FaceRunRecordError,
        PerfLegError,
    ) as exc:
        sys.exit(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
