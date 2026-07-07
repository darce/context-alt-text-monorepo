"""Eval-harness CLI: fetch / score / run / seed-roster.

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
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scene.config.profiles import PROFILE_SPECS, DescriptionProfile
from scene.domain.description import DescriptionAdapterKind

from .manifest import GoldenManifest, ManifestError, load_manifest
from .remote_client import RemoteClientError, RemoteSceneClient
from .report import ReportError, build_reports, score_run_record
from .schema import SCHEMA, DocKind
from .seed_roster import seed

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
    ``cost_per_image_usd`` (the provider's published per-request price) yields
    ``est_cost_usd``; ``max_cost_usd`` aborts *before* the paid call that would
    push ``spent_usd`` + this run's estimate past the cap (``spent_usd`` carries
    spend from earlier legs of a matrix invocation).
    """
    images_root = Path(images_dir)
    entries = manifest.entries[:limit] if limit else manifest.entries
    items: list[dict[str, Any]] = []
    consecutive_failures = 0

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
            provenance["est_cost_usd"] = round(cost_per_image_usd * len(items), 6)
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
            projected = spent_usd + cost_per_image_usd * (len(items) + 1)
            if projected > max_cost_usd:
                raise MaxCostExceededError(
                    f"next paid call would raise estimated spend to ${projected:.4f} "
                    f"(> --max-cost ${max_cost_usd:.4f}); aborting before {entry.path}",
                    partial_record=_record(aborted=True),
                )
        image_path = images_root / entry.path
        item: dict[str, Any] = {
            "media_id": entry.media_id,
            "path": entry.path,
            "describe": None,
            "identities": [],
            "face_count": 0,
            "error": None,
            "latency_s": None,
        }
        item_started = time.monotonic()
        try:
            image_bytes = image_path.read_bytes()
            item["describe"] = client.describe(
                image_bytes=image_bytes,
                filename=image_path.name,
                media_id=entry.media_id,
                context_pack=entry.context_pack.model_dump(exclude_none=True),
            )
            job_id = client.analyze([(entry.media_id, image_path.name, image_bytes)])
            client.wait_job(job_id)
            identities_payload = client.media_identities([entry.media_id])
            names, face_count = _extract_identities(identities_payload, entry.media_id)
            item["identities"] = names
            item["face_count"] = face_count
        except Exception as exc:  # noqa: BLE001 — per-item isolation is the contract (rg-007)
            item["error"] = f"{type(exc).__name__}: {exc}"
            item["latency_s"] = round(time.monotonic() - item_started, 3)
            consecutive_failures += 1
            if consecutive_failures >= stall_limit:
                items.append(item)
                raise BoundedStallError(
                    f"{consecutive_failures} consecutive item failures (last: {entry.path}); aborting run",
                    partial_record=_record(aborted=True),
                ) from exc
        else:
            item["latency_s"] = round(time.monotonic() - item_started, 3)
            consecutive_failures = 0
            if provider is not None:
                disclosure = item["describe"].get("provider_disclosure") if isinstance(item["describe"], dict) else None
                corroborated = (
                    isinstance(disclosure, dict)
                    and disclosure.get("provider") == "hosted"
                    and disclosure.get("left_service_boundary") is True
                )
                if not corroborated:
                    items.append(item)
                    raise ProviderMismatchError(
                        f"--provider {provider!r} claimed but {entry.path}'s describe response does not "
                        f"disclose a hosted provider (provider_disclosure={disclosure!r}); the service "
                        "profile is fixed server-side by ACX_DESCRIPTION_ADAPTER — refusing to stamp "
                        "mislabeled evidence",
                        partial_record=_record(aborted=True),
                    )
        items.append(item)

    return _record()


def _extract_identities(payload: Any, media_id: int) -> tuple[list[str], int]:
    """Normalize /media/identities rows for one media_id -> (names, face_count)."""
    rows = payload if isinstance(payload, list) else []
    names: list[str] = []
    face_count = 0
    for row in rows:
        if not isinstance(row, dict) or int(row.get("media_id", -1)) != media_id:
            continue
        face_count += 1
        label = row.get("label") or row.get("cluster_label") or row.get("name")
        if label and bool(row.get("user_confirmed", True)):
            names.append(str(label))
    return sorted(set(names)), face_count


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
    api_key = os.environ.get("ACX_EVAL_API_KEY", "")
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
            # --max-cost caps the whole invocation, not each matrix leg.
            spent_usd += args.cost_per_image * len(record["items"])
        record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        record_paths.append(str(record_path))
        print(record_path)
    # Never prune records this invocation just wrote (S3-07 across the matrix).
    prune_out_dir(str(OUT_DIR), keep=max(args.keep, len(record_paths)))
    return record_paths


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
    json_doc, md_doc = build_reports(record, entries, ignore_list=ignore_list, score_manifest_sha256=manifest_sha)
    if args.check_determinism:
        json_again, md_again = build_reports(
            record, entries, ignore_list=ignore_list, score_manifest_sha256=manifest_sha
        )
        if json_doc != json_again or md_doc != md_again:
            sys.exit("determinism check FAILED: re-score produced different output")
        print("determinism check passed: re-score is bit-identical")
    base = record_path.with_suffix("")
    json_path, md_path = Path(f"{base}-report.json"), Path(f"{base}-report.md")
    json_path.write_text(json_doc)
    md_path.write_text(md_doc)
    scored = score_run_record(record, entries, ignore_list=ignore_list, score_manifest_sha256=manifest_sha)
    print(md_path)
    print(
        f"scored={scored['counts']['scored']}/{scored['counts']['total']} "
        f"insertion_rate={scored['caption']['insertion_rate']} "
        f"wrong_names={len(scored['faces']['identification']['wrong_names'])}"
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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="eval_harness", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def _common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--manifest", default="scene/tests/seed/golden.json")
        p.add_argument("--limit", type=int, default=None)
        p.add_argument("--stall-limit", type=int, default=DEFAULT_STALL_LIMIT)
        p.add_argument("--keep", type=_keep_arg, default=DEFAULT_KEEP)
        p.add_argument("--llm-judge", action="store_true", help="stub — not implemented (§6c)")
        p.add_argument("--check-determinism", action="store_true")

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
    score_p.add_argument("--run-record", required=True)
    score_p.set_defaults(func=_cmd_score)

    run_p = sub.add_parser("run", help="fetch then score")
    _common(run_p)
    _provider_flags(run_p)
    run_p.set_defaults(func=_cmd_run)

    seed_p = sub.add_parser("seed-roster", help="idempotent eval-tenant roster seeding")
    seed_p.add_argument("--entities", required=True, help="<GOLDEN_IMAGES_DIR>/mock_entities")
    seed_p.set_defaults(func=_cmd_seed_roster)

    args = parser.parse_args(argv)
    if getattr(args, "max_cost", None) is not None and getattr(args, "cost_per_image", None) is None:
        parser.error("--max-cost requires --cost-per-image (the cap is estimated spend; without a price it is a no-op)")
    try:
        args.func(args)
    except (
        ManifestError,
        RemoteClientError,
        BoundedStallError,
        MaxCostExceededError,
        ProviderMismatchError,
        ReportError,
    ) as exc:
        sys.exit(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
