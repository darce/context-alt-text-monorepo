"""E20-FUSION fusion eval runner — staged fusion vs ad-hoc over bakeoff_golden.json.

DISTINCT from ``bakeoff.py`` (FUSION-PR-01): bakeoff emits raw single-VLM captions;
this module drives ``VisualFactsService`` / Stage-2 reconcile with stub/seeded
adapters and emits acx-eval/v1 run records that ``report.build_reports`` can
score. No live VLM calls, no network.

Mis-attachment is scored here (report.py is unchanged): expected_attachments
labels vs emitted attachment_provenance. Caption Must-Right / insertion /
Easy-Wrong (stub tier) come from ``build_reports``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from scene.application.description_adapter import AdapterResult
from scene.application.identity_merge import ConfirmedFace, NamingPolicy, NormalizedBox, PhraseBox
from scene.application.seeded_adapter import SeededDescriptionAdapter
from scene.application.visual_facts_service import VisualFactsService
from scene.interface_adapters.http.schemas.requests import (
    ContextPack,
    IdentityContext,
    IdentityContextItem,
    IdentityPolicyContext,
    TaxonomyTermContext,
)

from .manifest import GoldenEntry, GoldenManifest, ManifestError, load_manifest
from .report import build_reports
from .schema import SCHEMA, DocKind

Mode = Literal["staged", "adhoc"]

_TENANT = uuid.UUID("00000000-0000-0000-0000-00000000f051")
_PERSON_PHRASE = "person"
_DEFAULT_CAPTION = f"A {_PERSON_PHRASE} standing outdoors near greenery."
_CLUSTER_SLUG_RE = re.compile(r"[^a-z0-9]+")
_PERSON_BOX = NormalizedBox(x=0.3, y=0.1, width=0.3, height=0.7)
_FACE_BOX = NormalizedBox(x=0.4, y=0.2, width=0.05, height=0.08)


@dataclass(frozen=True)
class MisAttachmentHit:
    """One expected fact that the run attached incorrectly."""

    path: str
    media_id: int
    fact_label: str
    fact_source: str
    expected_decision: str
    actual_decision: str | None
    expected_visible: bool
    actual_visible: bool | None
    reason: str


def _cluster_id(name: str) -> str:
    slug = _CLUSTER_SLUG_RE.sub("-", name.lower()).strip("-")
    return f"cluster-{slug}"


def _identity_id(name: str) -> str:
    slug = _CLUSTER_SLUG_RE.sub("-", name.lower()).strip("-")
    return f"identity-{slug}"


def _slug(label: str) -> str:
    return _CLUSTER_SLUG_RE.sub("-", label.lower()).strip("-") or "term"


def build_typed_context_pack(entry: GoldenEntry) -> ContextPack | None:
    """Build a real HTTP ContextPack from expected_attachments labels.

    Legacy title/caption/description alone is not a typed pack
    (``_coerce_context_pack`` returns None). Empty pack when no labels.
    """
    expected = list(entry.expected_attachments)
    if not expected:
        return None

    identities: list[IdentityContextItem] = []
    taxonomy: list[TaxonomyTermContext] = []

    for exp in expected:
        src = exp.fact_source
        if src == "identity":
            # Unconfirmed: no cluster/identity ids (liam-maloney painting).
            if exp.review_reason == "unconfirmed_identity":
                identities.append(IdentityContextItem(name=exp.fact_label))
            else:
                identities.append(
                    IdentityContextItem(
                        name=exp.fact_label,
                        identity_id=_identity_id(exp.fact_label),
                        cluster_id=_cluster_id(exp.fact_label),
                        source="roster",
                    )
                )
        elif src == "event":
            taxonomy.append(
                TaxonomyTermContext(taxonomy="event", name=exp.fact_label, slug=_slug(exp.fact_label))
            )
        elif src == "place":
            taxonomy.append(
                TaxonomyTermContext(taxonomy="place", name=exp.fact_label, slug=_slug(exp.fact_label))
            )

    if not identities and not taxonomy:
        return None

    person_naming = "allowed" if entry.policy.recognition_enabled else "disabled"
    return ContextPack(
        identity=(
            IdentityContext(
                policy=IdentityPolicyContext(person_naming=person_naming),
                identities=identities,
                review_reasons=[],
            )
            if identities
            else None
        ),
        taxonomy_terms=taxonomy,
    )


def _make_face(label: str) -> ConfirmedFace:
    """Real ConfirmedFace shape (merge.py) for detector-backed object attach."""
    return ConfirmedFace(
        identity_id=_identity_id(label),
        cluster_id=_cluster_id(label),
        roster_id=f"roster-{_slug(label)}",
        label=label,
        detection_confidence=0.95,
        box=_FACE_BOX,
    )


def _make_person_phrase_box(caption: str) -> PhraseBox:
    start = caption.lower().index(_PERSON_PHRASE)
    return PhraseBox(
        phrase=caption[start : start + len(_PERSON_PHRASE)],
        span_start=start,
        span_end=start + len(_PERSON_PHRASE),
        box=_PERSON_BOX,
    )


def _caption_for_entry(entry: GoldenEntry, *, mode: Mode) -> str:
    """Deterministic caption: weave must_right / present names for insertion scoring."""
    pack = entry.context_pack
    bits: list[str] = []
    if entry.policy.recognition_enabled:
        names = list(entry.must_right) or list(entry.present_identities)
        if names:
            bits.append(" and ".join(names))
    # Free-form scene cue (not asserted as visible attachment).
    if pack.caption:
        bits.append(str(pack.caption))
    if mode == "adhoc":
        # Ad-hoc: assert event/place labels as if visible (mis-attachment class).
        for exp in entry.expected_attachments:
            if exp.fact_source in {"event", "place"} and exp.visible is False:
                bits.append(f"clearly shows a {exp.fact_label}")
            if exp.decision == "dropped" and exp.fact_source == "identity":
                # Object-assert the dropped name anyway (wrong altitude).
                bits.append(f"{exp.fact_label} is prominently visible in the frame")
    body = ". ".join(bits) if bits else _DEFAULT_CAPTION
    if _PERSON_PHRASE not in body.lower():
        body = f"{body}. A {_PERSON_PHRASE} is present."
    return body


class _FusionStubAdapter:
    """Deterministic DescriptionAdapter: fixed caption + optional person phrase box."""

    kind = SeededDescriptionAdapter.kind
    model_id = "fusion-eval-stub"
    model_version = "1"
    prompt_or_task_version = "e20-fusion-slice4"

    def __init__(self, *, caption: str, with_person_box: bool) -> None:
        self._caption = caption
        self._with_person_box = with_person_box

    def describe(self, *, image_bytes: bytes, context: Any) -> AdapterResult:
        phrase_boxes: tuple[PhraseBox, ...] = ()
        if self._with_person_box and _PERSON_PHRASE in self._caption.lower():
            phrase_boxes = (_make_person_phrase_box(self._caption),)
        return AdapterResult(
            caption=self._caption,
            objects=(_PERSON_PHRASE, "scene"),
            ocr_text=None,
            alt_text_draft=self._caption,
            context_sources=("context_pack",) if context else (),
            context_applied=bool(context),
            phrase_boxes=phrase_boxes,
        )


def _faces_for_entry(entry: GoldenEntry) -> list[ConfirmedFace]:
    """Detector-backed faces only for identities expected to object-attach."""
    faces: list[ConfirmedFace] = []
    for exp in entry.expected_attachments:
        if exp.fact_source != "identity":
            continue
        if exp.decision != "object":
            continue
        faces.append(_make_face(exp.fact_label))
    return faces


def _adhoc_provenance(entry: GoldenEntry) -> list[dict[str, Any]]:
    """Naive ad-hoc: every expected fact asserted object-visible (mis-attachment baseline)."""
    out: list[dict[str, Any]] = []
    for exp in entry.expected_attachments:
        fid = exp.fact_id or f"{exp.fact_source}:{_slug(exp.fact_label)}"
        out.append(
            {
                "fact_id": fid,
                "fact_source": exp.fact_source,
                "fact_label": exp.fact_label,
                "decision": "object",
                "altitude": "object",
                "target_evidence": "adhoc-injection",
                "review_reason": None,
                "visible": True,
            }
        )
    return out


async def _run_staged_item(entry: GoldenEntry, image_bytes: bytes) -> dict[str, Any]:
    caption = _caption_for_entry(entry, mode="staged")
    pack = build_typed_context_pack(entry)
    faces = _faces_for_entry(entry)
    with_box = any(e.decision == "object" and e.fact_source == "identity" for e in entry.expected_attachments)
    adapter = _FusionStubAdapter(caption=caption, with_person_box=with_box)
    svc = VisualFactsService(adapter=adapter, repository=None)
    context = pack.model_dump(exclude_none=True) if pack is not None else None
    response = await svc.describe(
        tenant_id=_TENANT,
        media_id=entry.media_id,
        image_bytes=image_bytes,
        context=context,
        confirmed_faces=faces,
        naming_policy=NamingPolicy(agreement_enabled=True) if entry.policy.recognition_enabled else None,
    )
    facts = []
    if response.attachment_provenance is not None:
        facts = [
            {
                "fact_id": f.fact_id,
                "fact_source": f.fact_source,
                "fact_label": f.fact_label,
                "decision": f.decision,
                "altitude": f.altitude,
                "target_evidence": f.target_evidence,
                "review_reason": f.review_reason,
                "visible": f.visible,
            }
            for f in response.attachment_provenance.facts
        ]
    return {
        "media_id": entry.media_id,
        "path": entry.path,
        "describe": {
            "alt_text_draft": response.alt_text_draft,
            "visual_facts": {
                "caption": response.visual_facts.caption,
                "objects": list(response.visual_facts.objects),
            },
            "adapter": response.adapter.value if hasattr(response.adapter, "value") else str(response.adapter),
            "model_id": response.model_id,
            "model_version": response.model_version,
            "cached": bool(response.cached),
            "attachment_provenance": {"facts": facts},
        },
        "identities": list(entry.present_identities) if entry.policy.recognition_enabled else [],
        "face_count": entry.face_count if entry.policy.recognition_enabled else 0,
        "error": None,
    }


def _run_adhoc_item(entry: GoldenEntry) -> dict[str, Any]:
    caption = _caption_for_entry(entry, mode="adhoc")
    return {
        "media_id": entry.media_id,
        "path": entry.path,
        "describe": {
            "alt_text_draft": caption,
            "visual_facts": {"caption": caption, "objects": [_PERSON_PHRASE]},
            "adapter": "adhoc-injection",
            "model_id": "adhoc-baseline",
            "model_version": "1",
            "cached": False,
            "attachment_provenance": {"facts": _adhoc_provenance(entry)},
        },
        "identities": list(entry.present_identities) if entry.policy.recognition_enabled else [],
        "face_count": entry.face_count if entry.policy.recognition_enabled else 0,
        "error": None,
    }


def _synthetic_image_bytes(entry: GoldenEntry) -> bytes:
    """Deterministic fake image bytes (no network, no GOLDEN_IMAGES_DIR required)."""
    material = f"{entry.path}:{entry.sha256}:{entry.media_id}".encode()
    return hashlib.sha256(material).digest() + b"\x89PNG\r\n\x1a\nfusion-eval"


def run_fusion_eval(
    manifest: GoldenManifest,
    *,
    mode: Mode,
    head_sha: str,
    started_at: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Walk bakeoff entries; emit acx-eval/v1 run_record for ``mode``."""
    entries = list(manifest.entries[:limit] if limit else manifest.entries)
    items: list[dict[str, Any]] = []
    for entry in entries:
        if mode == "adhoc":
            items.append(_run_adhoc_item(entry))
            continue
        try:
            item = asyncio.run(_run_staged_item(entry, _synthetic_image_bytes(entry)))
        except Exception as exc:  # noqa: BLE001 — per-item isolation (rg-007)
            items.append(
                {
                    "media_id": entry.media_id,
                    "path": entry.path,
                    "describe": None,
                    "identities": [],
                    "face_count": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        else:
            items.append(item)

    manifest_bytes = json.dumps(
        {
            "manifest_version": manifest.manifest_version,
            "roster": manifest.roster,
            "entries": [e.model_dump(mode="json") for e in manifest.entries],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return {
        "schema": SCHEMA,
        "kind": DocKind.RUN_RECORD.value,
        "provenance": {
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "base_url": f"fusion-runner://{mode}",
            "head_sha": head_sha,
            "started_at": started_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "fusion_mode": mode,
        },
        "items": items,
    }


def score_misattachments(
    run_record: dict[str, Any],
    manifest: GoldenManifest,
) -> dict[str, Any]:
    """Compare attachment_provenance against expected_attachments labels.

    A mis-attachment is any expected fact whose actual decision/visible flags
    disagree with the label (wrong altitude, asserted-visible when not, etc.).
    """
    by_id = {e.media_id: e for e in manifest.entries}
    hits: list[MisAttachmentHit] = []
    labeled = 0
    for item in run_record.get("items", []):
        entry = by_id.get(int(item["media_id"]))
        if entry is None or not entry.expected_attachments:
            continue
        if item.get("error"):
            for exp in entry.expected_attachments:
                labeled += 1
                hits.append(
                    MisAttachmentHit(
                        path=entry.path,
                        media_id=entry.media_id,
                        fact_label=exp.fact_label,
                        fact_source=exp.fact_source,
                        expected_decision=exp.decision,
                        actual_decision=None,
                        expected_visible=exp.visible,
                        actual_visible=None,
                        reason="item_error",
                    )
                )
            continue
        facts = ((item.get("describe") or {}).get("attachment_provenance") or {}).get("facts") or []
        by_key = {_match_key(f.get("fact_source"), f.get("fact_label"), f.get("fact_id")): f for f in facts}
        for exp in entry.expected_attachments:
            labeled += 1
            actual = by_key.get(_match_key(exp.fact_source, exp.fact_label, exp.fact_id))
            if actual is None:
                # Try label+source only.
                actual = next(
                    (
                        f
                        for f in facts
                        if str(f.get("fact_source")) == exp.fact_source
                        and str(f.get("fact_label")).lower() == exp.fact_label.lower()
                    ),
                    None,
                )
            if actual is None:
                hits.append(
                    MisAttachmentHit(
                        path=entry.path,
                        media_id=entry.media_id,
                        fact_label=exp.fact_label,
                        fact_source=exp.fact_source,
                        expected_decision=exp.decision,
                        actual_decision=None,
                        expected_visible=exp.visible,
                        actual_visible=None,
                        reason="missing_provenance",
                    )
                )
                continue
            actual_decision = str(actual.get("decision"))
            actual_visible = bool(actual.get("visible"))
            if actual_decision != exp.decision or actual_visible != exp.visible:
                hits.append(
                    MisAttachmentHit(
                        path=entry.path,
                        media_id=entry.media_id,
                        fact_label=exp.fact_label,
                        fact_source=exp.fact_source,
                        expected_decision=exp.decision,
                        actual_decision=actual_decision,
                        expected_visible=exp.visible,
                        actual_visible=actual_visible,
                        reason="decision_or_visible_mismatch",
                    )
                )
            elif exp.review_reason and actual.get("review_reason") != exp.review_reason:
                hits.append(
                    MisAttachmentHit(
                        path=entry.path,
                        media_id=entry.media_id,
                        fact_label=exp.fact_label,
                        fact_source=exp.fact_source,
                        expected_decision=exp.decision,
                        actual_decision=actual_decision,
                        expected_visible=exp.visible,
                        actual_visible=actual_visible,
                        reason=f"review_reason_mismatch expected={exp.review_reason!r} actual={actual.get('review_reason')!r}",
                    )
                )
    return {
        "labeled_facts": labeled,
        "misattachments": len(hits),
        "hits": [
            {
                "path": h.path,
                "media_id": h.media_id,
                "fact_label": h.fact_label,
                "fact_source": h.fact_source,
                "expected_decision": h.expected_decision,
                "actual_decision": h.actual_decision,
                "expected_visible": h.expected_visible,
                "actual_visible": h.actual_visible,
                "reason": h.reason,
            }
            for h in hits
        ],
    }


def _match_key(fact_source: Any, fact_label: Any, fact_id: Any) -> str:
    if fact_id:
        return f"id:{fact_id}"
    return f"{fact_source}:{str(fact_label).lower()}"


def manifest_entries_as_dicts(manifest: GoldenManifest) -> list[dict[str, Any]]:
    """Shapes expected by ``report.score_run_record`` / ``build_reports``."""
    return [
        {
            "path": e.path,
            "media_id": e.media_id,
            "face_count": e.face_count,
            "present_identities": list(e.present_identities),
            "must_right": list(e.must_right),
            "easy_wrong": list(e.easy_wrong),
            "policy": {"recognition_enabled": e.policy.recognition_enabled},
        }
        for e in manifest.entries
    ]


def _head_sha() -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL)
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "0" * 40


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default=str(Path(__file__).resolve().parents[2] / "scene" / "tests" / "seed" / "bakeoff_golden.json"),
    )
    parser.add_argument("--mode", choices=("staged", "adhoc", "both"), default="both")
    # fusion_runner.py → eval_harness → scripts → service → apps → monorepo root
    parser.add_argument("--out-dir", default=str(Path(__file__).resolve().parents[4] / "docs" / "tasks" / "20.0"))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.manifest)
    except ManifestError as exc:
        print(f"manifest error: {exc}", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    head = _head_sha()
    modes: list[Mode] = ["staged", "adhoc"] if args.mode == "both" else [args.mode]  # type: ignore[list-item]
    entries = manifest_entries_as_dicts(manifest)

    for mode in modes:
        record = run_fusion_eval(manifest, mode=mode, head_sha=head, limit=args.limit)
        mis = score_misattachments(record, manifest)
        json_report, md_report = build_reports(record, entries, score_manifest_sha256=record["provenance"]["manifest_sha256"])
        # Append mis-attachment summary to markdown (report.py unchanged).
        md_report = md_report.rstrip() + "\n\n## Mis-attachment (E20-FUSION)\n\n"
        md_report += f"- labeled facts: {mis['labeled_facts']}\n"
        md_report += f"- mis-attachments: {mis['misattachments']}\n"
        if mis["hits"]:
            for h in mis["hits"]:
                md_report += (
                    f"- `{h['path']}` {h['fact_source']}/{h['fact_label']}: "
                    f"expected {h['expected_decision']} visible={h['expected_visible']}, "
                    f"actual {h['actual_decision']} visible={h['actual_visible']} ({h['reason']})\n"
                )
        else:
            md_report += "- none\n"
        md_report += "\n"

        stem = f"E20-FUSION-{mode}"
        (out_dir / f"{stem}-run-record.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        (out_dir / f"{stem}-report.json").write_text(json_report)
        (out_dir / f"{stem}-report.md").write_text(md_report)
        (out_dir / f"{stem}-misattachment.json").write_text(json.dumps(mis, indent=2, sort_keys=True) + "\n")
        print(f"{mode}: misattachments={mis['misattachments']}/{mis['labeled_facts']} → {out_dir / stem}-report.md")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
