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
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .manifest import GoldenManifest, ManifestError, load_manifest
from .remote_client import RemoteClientError, RemoteSceneClient
from .report import ReportError, build_reports, score_run_record
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


class BoundedStallError(RuntimeError):
    """Aborted after too many consecutive per-item failures (rg-007).

    Carries the partial run record (``aborted: true``) so an aborted run is
    still diagnosable — the per-item errors are the whole point of the abort.
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
) -> dict[str, Any]:
    """Walk manifest entries sequentially; isolate per-item failures; bound stalls."""
    images_root = Path(images_dir)
    entries = manifest.entries[:limit] if limit else manifest.entries
    items: list[dict[str, Any]] = []
    consecutive_failures = 0

    def _record(aborted: bool = False) -> dict[str, Any]:
        record: dict[str, Any] = {
            "schema": SCHEMA,
            "kind": DocKind.RUN_RECORD.value,
            "provenance": {
                "manifest_sha256": _manifest_sha(manifest),
                "base_url": getattr(client, "base_url", "unknown"),
                "head_sha": head_sha,
                "started_at": started_at,
            },
            "items": items,
        }
        if aborted:
            record["aborted"] = True
        return record

    for entry in entries:
        image_path = images_root / entry.path
        item: dict[str, Any] = {
            "media_id": entry.media_id,
            "path": entry.path,
            "describe": None,
            "identities": [],
            "face_count": 0,
            "error": None,
        }
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
            consecutive_failures += 1
            if consecutive_failures >= stall_limit:
                items.append(item)
                raise BoundedStallError(
                    f"{consecutive_failures} consecutive item failures (last: {entry.path}); aborting run",
                    partial_record=_record(aborted=True),
                ) from exc
        else:
            consecutive_failures = 0
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


def _cmd_fetch(args: argparse.Namespace) -> str:
    _reject_llm_judge(args)
    base_url, api_key, tenant_id = _require_live_env()
    images_dir = _images_dir()
    manifest = load_manifest(args.manifest, images_dir=images_dir)
    client = RemoteSceneClient(base_url=base_url, api_key=api_key, tenant_id=tenant_id)
    started_at = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    OUT_DIR.mkdir(exist_ok=True)
    stamp = started_at.replace(":", "").replace("-", "").replace("T", "-").rstrip("Z")
    record_path = OUT_DIR / f"run-{stamp}.json"
    try:
        record = fetch_run_record(
            manifest,
            images_dir,
            client,
            head_sha=_head_sha(),
            limit=args.limit,
            stall_limit=args.stall_limit,
            started_at=started_at,
        )
    except BoundedStallError as exc:
        aborted_path = OUT_DIR / f"run-{stamp}-aborted.json"
        aborted_path.write_text(json.dumps(exc.partial_record, indent=2, sort_keys=True) + "\n")
        sys.exit(f"BoundedStallError: {exc} — partial record saved to {aborted_path}")
    finally:
        client.close()
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    prune_out_dir(str(OUT_DIR), keep=args.keep)
    print(record_path)
    return str(record_path)


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
    record_path = _cmd_fetch(args)
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

    fetch_p = sub.add_parser("fetch", help="manifest -> remote calls -> run record")
    _common(fetch_p)
    fetch_p.set_defaults(func=_cmd_fetch)

    score_p = sub.add_parser("score", help="run record -> reports (pure, offline)")
    _common(score_p)
    score_p.add_argument("--run-record", required=True)
    score_p.set_defaults(func=_cmd_score)

    run_p = sub.add_parser("run", help="fetch then score")
    _common(run_p)
    run_p.set_defaults(func=_cmd_run)

    seed_p = sub.add_parser("seed-roster", help="idempotent eval-tenant roster seeding")
    seed_p.add_argument("--entities", required=True, help="<GOLDEN_IMAGES_DIR>/mock_entities")
    seed_p.set_defaults(func=_cmd_seed_roster)

    scenes_p = sub.add_parser("seed-scenes", help="idempotent eval-tenant scene-image seeding (E19-4a bboxes)")
    scenes_p.add_argument("--manifest", default="scene/tests/seed/golden.json")
    scenes_p.set_defaults(func=_cmd_seed_scenes)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (ManifestError, RemoteClientError, BoundedStallError, ReportError) as exc:
        sys.exit(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
