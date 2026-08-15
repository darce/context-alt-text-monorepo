"""E20-FUSION fusion eval runner — staged fusion vs ad-hoc over bakeoff_golden.json.

DISTINCT from ``bakeoff.py`` (FUSION-PR-01): bakeoff emits raw single-VLM captions;
this module drives ``VisualFactsService`` / Stage-2 reconcile with stub/seeded
adapters and emits acx-eval/v1 run records that ``report.build_reports`` can
score. No live VLM calls, no network.

Input/label separation (S4A-03): harness INPUTS (context pack, confirmed
faces, phrase-box geometry) derive only from raw fixture data — the entry's
``context_pack`` text, ``present_identities``, ``policy``, the roster, and the
optional ``context_pack.eval_scenario`` / ``context_pack.taxonomy_terms``
fixture fields. ``expected_attachments`` labels are consumed ONLY by
``score_misattachments`` as expectations, never fed back as inputs.

Face geometry mirrors real ``merge.py`` containment semantics: each detected
identity gets a distinct, non-overlapping face box whose center falls inside
exactly one person phrase box, so multi-identity entries genuinely exercise
1:1 discrimination (identical geometry would drop as ``ambiguous_grounding``).

Ad-hoc arm (S4A-02): drives the SAME ``VisualFactsService.describe`` path with
the fusion stage effectively disabled — legacy free-form context (title/
caption/description) is not a typed ContextPack, so Stage-2 emits no per-fact
provenance, exactly like today's ad-hoc WP flow. Attachment claims are then
DERIVED from what the generated ad-hoc caption actually asserts (a context
fact woven into the caption is presented as visual content — the
mis-attachment failure mode), not hardcoded. Construction limits are
documented in the decision memo.

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
from collections.abc import Sequence
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
_PERSON_WORD_RE = re.compile(r"\bperson\b", re.IGNORECASE)
_DEFAULT_CAPTION = f"A {_PERSON_PHRASE} standing outdoors near greenery."
_CLUSTER_SLUG_RE = re.compile(r"[^a-z0-9]+")
_ADHOC_EVIDENCE = "adhoc-caption-assertion"

# Taxonomy keys the fixture may carry that map to event/place fact sources
# (mirrors reconcile.py's `_EVENT_TAXONOMIES` / `_PLACE_TAXONOMIES` MVP subset).
_EVENT_TAXONOMY = "event"
_PLACE_TAXONOMY = "place"


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


# ---------------------------------------------------------------------------
# Raw-fixture input derivation (S4A-03: no expected_attachments reads here).
# ---------------------------------------------------------------------------


def _context_text(entry: GoldenEntry) -> str:
    pack = entry.context_pack
    return " ".join(str(part) for part in (pack.title, pack.caption, pack.description) if part)


def _pack_extra(entry: GoldenEntry) -> dict[str, Any]:
    return dict(entry.context_pack.model_extra or {})


def _fixture_taxonomy_terms(entry: GoldenEntry) -> list[dict[str, Any]]:
    """WP-shaped taxonomy terms vendored on the fixture context pack."""
    raw = _pack_extra(entry).get("taxonomy_terms")
    if not isinstance(raw, list):
        return []
    return [t for t in raw if isinstance(t, dict) and t.get("taxonomy") and t.get("name")]


def _undetected_identities(entry: GoldenEntry) -> frozenset[str]:
    """Fixture scenario: roster identities the face detector missed at runtime."""
    scenario = _pack_extra(entry).get("eval_scenario")
    if not isinstance(scenario, dict):
        return frozenset()
    raw = scenario.get("undetected_identities")
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(str(name) for name in raw)


def _mentioned_roster_names(entry: GoldenEntry, roster: Sequence[str]) -> list[str]:
    """Roster names the WP context text actually mentions, in first-mention order."""
    text = _context_text(entry).lower()
    hits = [(text.index(name.lower()), name) for name in roster if name.lower() in text]
    return [name for _, name in sorted(hits)]


def _detected_identities(entry: GoldenEntry) -> list[str]:
    """Roster faces the (simulated) detector confirmed on this image."""
    if not entry.policy.recognition_enabled:
        return []
    undetected = _undetected_identities(entry)
    return [name for name in entry.present_identities if name not in undetected]


def build_typed_context_pack(entry: GoldenEntry, roster: Sequence[str]) -> ContextPack | None:
    """Build a real HTTP ContextPack from raw fixture data (never from labels).

    Identity items are the roster names mentioned in the entry's WP context
    text: site-confirmed persons (``present_identities``) carry recognition
    ids; mentioned-but-not-present names ship name-only (unconfirmed).
    Taxonomy terms come from the fixture's ``context_pack.taxonomy_terms``.
    Legacy title/caption/description alone is not a typed pack; empty pack
    when nothing structurable is present.
    """
    identities: list[IdentityContextItem] = []
    for name in _mentioned_roster_names(entry, roster):
        if name in entry.present_identities:
            identities.append(
                IdentityContextItem(
                    name=name,
                    identity_id=_identity_id(name),
                    cluster_id=_cluster_id(name),
                    source="roster",
                )
            )
        else:
            identities.append(IdentityContextItem(name=name))

    taxonomy = [
        TaxonomyTermContext(
            taxonomy=str(term["taxonomy"]),
            name=str(term["name"]),
            slug=(str(term["slug"]) if term.get("slug") else _slug(str(term["name"]))),
        )
        for term in _fixture_taxonomy_terms(entry)
    ]

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


def _derived_facts(entry: GoldenEntry, roster: Sequence[str]) -> list[tuple[str, str, str]]:
    """(fact_id, fact_source, fact_label) triples the derived pack yields.

    Fact-id scheme mirrors reconcile.py (`_identity_fact_id` / taxonomy ids)
    so ad-hoc claims and staged provenance stay comparable.
    """
    out: list[tuple[str, str, str]] = []
    for index, name in enumerate(_mentioned_roster_names(entry, roster)):
        if name in entry.present_identities:
            out.append((f"identity:cluster:{_cluster_id(name)}", "identity", name))
        else:
            out.append((f"identity:{index}:{name}", "identity", name))
    for term in _fixture_taxonomy_terms(entry):
        taxonomy = str(term["taxonomy"]).casefold()
        name = str(term["name"])
        slug = str(term["slug"]) if term.get("slug") else _slug(name)
        if taxonomy == _EVENT_TAXONOMY:
            out.append((f"event:{slug}", "event", name))
        elif taxonomy == _PLACE_TAXONOMY:
            out.append((f"place:{slug}", "place", name))
        else:
            out.append((f"taxonomy:{taxonomy}:{slug}", "taxonomy", name))
    return out


# ---------------------------------------------------------------------------
# Distinct face/phrase geometry (mirrors merge.py containment semantics).
# ---------------------------------------------------------------------------


def _person_box(index: int) -> NormalizedBox:
    """Non-overlapping person phrase boxes laid out left-to-right."""
    return NormalizedBox(x=0.02 + 0.24 * index, y=0.08, width=0.20, height=0.72)


def _face_box(index: int) -> NormalizedBox:
    """Small face box whose center falls inside person box ``index`` only."""
    return NormalizedBox(x=0.095 + 0.24 * index, y=0.30, width=0.05, height=0.08)


def _make_face(label: str, index: int) -> ConfirmedFace:
    """Real ConfirmedFace shape (merge.py) with per-identity distinct geometry."""
    return ConfirmedFace(
        identity_id=_identity_id(label),
        cluster_id=_cluster_id(label),
        roster_id=f"roster-{_slug(label)}",
        label=label,
        detection_confidence=0.95,
        box=_face_box(index),
    )


def _person_phrase_boxes(caption: str, count: int) -> tuple[PhraseBox, ...]:
    """One grounded ``person`` span per detected face, each with its own box."""
    if count <= 0:
        return ()
    matches = list(_PERSON_WORD_RE.finditer(caption))[:count]
    return tuple(
        PhraseBox(
            phrase=caption[m.start() : m.end()],
            span_start=m.start(),
            span_end=m.end(),
            box=_person_box(i),
        )
        for i, m in enumerate(matches)
    )


def _caption_for_entry(entry: GoldenEntry, *, mode: Mode, detected: Sequence[str]) -> str:
    """Deterministic caption stub.

    staged: detected names + WP caption cue + one groundable ``person``
    sentence per detected face (containment targets).
    adhoc: parrots the full injected WP context verbatim — title, caption and
    description woven into the caption body, indistinguishable from visual
    content (today's ad-hoc prompt-injection behavior).
    """
    pack = entry.context_pack
    bits: list[str] = []
    if entry.policy.recognition_enabled and detected:
        bits.append(" and ".join(detected))
    if mode == "staged":
        if pack.caption:
            bits.append(str(pack.caption))
        for i in range(len(detected)):
            bits.append(f"A {_PERSON_PHRASE} stands at position {i + 1} from the left")
    else:
        for part in (pack.title, pack.caption, pack.description):
            if part:
                bits.append(str(part))
    body = ". ".join(bits) if bits else _DEFAULT_CAPTION
    if _PERSON_PHRASE not in body.lower():
        body = f"{body}. A {_PERSON_PHRASE} is present."
    return body


class _FusionStubAdapter:
    """Deterministic DescriptionAdapter: fixed caption + pre-built phrase boxes."""

    kind = SeededDescriptionAdapter.kind
    model_version = "1"
    prompt_or_task_version = "e20-fusion-slice4"

    def __init__(
        self,
        *,
        caption: str,
        phrase_boxes: tuple[PhraseBox, ...] = (),
        model_id: str = "fusion-eval-stub",
    ) -> None:
        self._caption = caption
        self._phrase_boxes = phrase_boxes
        self.model_id = model_id

    def describe(self, *, image_bytes: bytes, context: Any) -> AdapterResult:
        return AdapterResult(
            caption=self._caption,
            objects=(_PERSON_PHRASE, "scene"),
            ocr_text=None,
            alt_text_draft=self._caption,
            context_sources=("context_pack",) if context else (),
            context_applied=bool(context),
            phrase_boxes=self._phrase_boxes,
        )


def _faces_for_entry(entry: GoldenEntry) -> list[ConfirmedFace]:
    """Detector-simulated confirmed faces: one distinct box per detected identity."""
    return [_make_face(name, index) for index, name in enumerate(_detected_identities(entry))]


def _reported_face_count(entry: GoldenEntry) -> int:
    if not entry.policy.recognition_enabled:
        return 0
    missed = len(_undetected_identities(entry) & set(entry.present_identities))
    return max(entry.face_count - missed, 0)


def _adhoc_claims(entry: GoldenEntry, roster: Sequence[str], caption: str) -> list[dict[str, Any]]:
    """Derive ad-hoc attachment claims from what the caption actually asserts.

    Ad-hoc injection has no altitude separation: any context fact woven into
    the caption is presented as visual content, so an asserted label scores as
    object-attached/visible; a label absent from the caption was effectively
    dropped. Nothing here reads expected_attachments.
    """
    lowered = caption.lower()
    out: list[dict[str, Any]] = []
    for fact_id, fact_source, fact_label in _derived_facts(entry, roster):
        asserted = fact_label.lower() in lowered
        out.append(
            {
                "fact_id": fact_id,
                "fact_source": fact_source,
                "fact_label": fact_label,
                "decision": "object" if asserted else "dropped",
                "altitude": "object" if asserted else "none",
                "target_evidence": _ADHOC_EVIDENCE if asserted else None,
                "review_reason": None,
                "visible": asserted,
            }
        )
    return out


async def _run_staged_item(entry: GoldenEntry, image_bytes: bytes, roster: Sequence[str]) -> dict[str, Any]:
    detected = _detected_identities(entry)
    caption = _caption_for_entry(entry, mode="staged", detected=detected)
    pack = build_typed_context_pack(entry, roster)
    faces = _faces_for_entry(entry)
    adapter = _FusionStubAdapter(
        caption=caption,
        phrase_boxes=_person_phrase_boxes(caption, len(faces)),
    )
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
        "identities": detected,
        "face_count": _reported_face_count(entry),
        "error": None,
    }


async def _run_adhoc_item(entry: GoldenEntry, image_bytes: bytes, roster: Sequence[str]) -> dict[str, Any]:
    """Ad-hoc arm through the SAME service path, fusion stage disabled.

    Legacy free-form context (title/caption/description) is not a typed
    ContextPack, so ``VisualFactsService`` runs no Stage-2 reconcile — exactly
    today's ad-hoc WP behavior. Claims are then parsed from the generated
    caption (see ``_adhoc_claims``), never hardcoded.
    """
    detected = _detected_identities(entry)
    caption = _caption_for_entry(entry, mode="adhoc", detected=detected)
    adapter = _FusionStubAdapter(caption=caption, model_id="fusion-eval-adhoc-stub")
    svc = VisualFactsService(adapter=adapter, repository=None)
    pack = entry.context_pack
    legacy_context = {
        key: str(value)
        for key, value in (("title", pack.title), ("caption", pack.caption), ("description", pack.description))
        if value
    }
    response = await svc.describe(
        tenant_id=_TENANT,
        media_id=entry.media_id,
        image_bytes=image_bytes,
        context=legacy_context or None,
        confirmed_faces=(),
        naming_policy=None,
    )
    service_facts = list(response.attachment_provenance.facts) if response.attachment_provenance else []
    if service_facts:  # legacy context must never reach Stage-2 (honest-baseline invariant)
        raise RuntimeError(
            f"ad-hoc arm unexpectedly produced {len(service_facts)} Stage-2 facts for {entry.path}; "
            "legacy context should not coerce to a typed ContextPack"
        )
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
            "attachment_provenance": {
                "facts": _adhoc_claims(entry, roster, response.visual_facts.caption),
                "derivation": _ADHOC_EVIDENCE,
            },
        },
        "identities": detected,
        "face_count": _reported_face_count(entry),
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
    roster = list(manifest.roster)
    items: list[dict[str, Any]] = []
    for entry in entries:
        runner = _run_adhoc_item if mode == "adhoc" else _run_staged_item
        try:
            item = asyncio.run(runner(entry, _synthetic_image_bytes(entry), roster))
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
    """Shapes expected by ``report.score_run_record`` / ``build_reports``.

    Stamps the parent ``annotation_mode`` onto every entry. The resolver
    reads the stamp (data wins); an explicit kwarg cannot widen a
    ``roster_only`` stamp to exhaustive.
    """
    mode = (
        manifest.annotation_mode.value
        if hasattr(manifest.annotation_mode, "value")
        else str(manifest.annotation_mode)
    )
    return [
        {
            "path": e.path,
            "media_id": e.media_id,
            "face_count": e.face_count,
            "present_identities": list(e.present_identities),
            "must_right": list(e.must_right),
            "easy_wrong": list(e.easy_wrong),
            "policy": {"recognition_enabled": e.policy.recognition_enabled},
            "annotation_mode": mode,
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
        json_report, md_report = build_reports(
            record,
            entries,
            score_manifest_sha256=record["provenance"]["manifest_sha256"],
        )
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
