"""CPU-only naming proposals over an original, unnamed description base.

Run generations and WordPress alt text are never mutated here. New runs carry
their replay inputs. Legacy runs may use only their exact cache key and an image
hash/dimensions receipt from WordPress, never the latest caption for a media ID.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from db.tenant_context import require_tenant_record
from scene.application import naming_preview_service as naming
from scene.application.description_repository import ImageDescriptionRepository
from scene.application.hashing import compute_context_hash, compute_image_hash
from scene.application.identity_merge import join
from scene.application.identity_merge.merge import NormalizedBox, PhraseBox, merge_identities, span_replaceable
from scene.application.identity_merge.policy import NamingPolicy

logger = logging.getLogger(__name__)


class DescriptionImageEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    media_id: int = Field(gt=0)
    image_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    width: int = Field(gt=0, le=100_000)
    height: int = Field(gt=0, le=100_000)


class _Phrase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    phrase: str
    span: list[int] = Field(min_length=2, max_length=2)
    box: list[float] = Field(min_length=4, max_length=4)


class NamingBase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1] = 1
    caption: str = Field(min_length=1)
    image_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    width: int = Field(gt=0, le=100_000)
    height: int = Field(gt=0, le=100_000)
    phrase_boxes: list[_Phrase] = Field(max_length=500)

    def boxes(self) -> list[PhraseBox]:
        boxes = [PhraseBox(p.phrase, p.span[0], p.span[1], NormalizedBox(*p.box)) for p in self.phrase_boxes]
        if any(not span_replaceable(self.caption, box) for box in boxes):
            raise ValueError("grounding no longer matches original caption")
        return boxes


def freeze_naming_base(*, caption: str, phrase_boxes: Sequence[PhraseBox], image_bytes: bytes) -> dict | None:
    dims = naming._image_dimensions(image_bytes)
    if dims is None or not caption:
        return None
    return NamingBase(
        caption=caption,
        image_hash=compute_image_hash(image_bytes),
        width=dims[0],
        height=dims[1],
        phrase_boxes=[
            _Phrase(
                phrase=p.phrase,
                span=[p.span_start, p.span_end],
                box=[p.box.x, p.box.y, p.box.width, p.box.height],
            )
            for p in phrase_boxes
        ],
    ).model_dump()


async def _legacy_base(session, *, tenant_id, item, evidence: DescriptionImageEvidence | None) -> NamingBase | None:
    provenance = item.provenance or {}
    if evidence is None or provenance.get("image_hash") != evidence.image_hash:
        return None
    keys = ("image_hash", "adapter", "model_id", "model_version", "prompt_or_task_version", "context_hash")
    if not all(isinstance(provenance.get(key), str) and provenance[key] for key in keys):
        return None
    if provenance["context_hash"] != compute_context_hash(None):
        return None  # legacy named prompt/context output is not an unnamed base
    row = await ImageDescriptionRepository(session).get_by_cache_key(
        tenant_id=tenant_id, **{key: provenance[key] for key in keys}
    )
    if row is None:
        return None
    caption = (row.visual_facts or {}).get("caption")
    # A cache hit is evidence only for this generation's original caption.
    # An arbitrary newer cache row, or a named final draft, is not a replay base.
    if not caption or caption != item.caption:
        return None
    return NamingBase(
        caption=caption,
        image_hash=evidence.image_hash,
        width=evidence.width,
        height=evidence.height,
        phrase_boxes=row.phrase_boxes or [],
    )


def _unambiguous_faces(base: NamingBase, boxes, faces, detected):
    detected_ids = {str(d.identity_id) for d in detected}
    faces = [f for f in faces if str(f.identity_id) in detected_ids]
    groundable = [p for p in boxes if span_replaceable(base.caption, p)]
    if not groundable:
        # One confirmed person among unnamed people is not a lone-person image.
        if detected_ids - {str(f.identity_id) for f in faces}:
            return [], boxes
        return faces, boxes
    safe_boxes = [p for p in groundable if sum(p.box.contains_point(*d.box.center) for d in detected) == 1]
    if not safe_boxes:
        return [], boxes
    return faces, safe_boxes


async def project_run_item_names(*, session, tenant_id, items, image_evidence=()) -> dict[int, dict]:
    """Return response-only text/provenance updates; never generate or persist."""
    evidence = {e.media_id: e for e in image_evidence}
    tenant = await require_tenant_record(session, tenant_id)
    policy = None
    updates = {}
    for item in items:
        if str(item.status) != "completed" or not item.alt_text_draft:
            continue
        provenance = dict(item.provenance or {})
        try:
            raw = provenance.get("naming_base")
            base = (
                NamingBase.model_validate(raw)
                if raw is not None
                else await _legacy_base(session, tenant_id=tenant_id, item=item, evidence=evidence.get(item.media_id))
            )
            if base is None or base.image_hash != provenance.get("image_hash"):
                raise ValueError("original naming base unavailable")
            current_image = evidence.get(item.media_id)
            if current_image is not None and current_image.image_hash != base.image_hash:
                raise ValueError("attachment changed since generation")
            boxes = base.boxes()
            if policy is None:
                policy = NamingPolicy(
                    agreement_enabled=tenant.naming_agreement_enabled,
                    suppressed_roster_ids=await naming.load_suppressed_roster_ids(session, tenant_id=tenant_id),
                )
            faces = await naming.load_confirmed_faces(
                session,
                tenant_id=tenant_id,
                media_id=item.media_id,
                image_width=base.width,
                image_height=base.height,
            )
            detected = await join.load_detected_faces(
                session,
                tenant_id=tenant_id,
                media_id=item.media_id,
                image_width=base.width,
                image_height=base.height,
            )
            faces, boxes = _unambiguous_faces(base, boxes, faces, detected)
            result = merge_identities(caption=base.caption, phrase_boxes=boxes, confirmed_faces=faces, policy=policy)
            provenance["naming"] = naming._provenance_model(result.provenance).model_dump(mode="json")
            provenance["naming_refresh"] = {"status": "current"}
            updates[item.media_id] = {"alt_text_draft": result.named_draft, "provenance": provenance}
        except (ValidationError, ValueError):
            provenance["naming_refresh"] = {"status": "unavailable", "reason": "original_base_unavailable"}
            updates[item.media_id] = {"provenance": provenance}
        except Exception:  # noqa: BLE001 - isolate unavailable naming from other image versions
            logger.exception("saved-description naming refresh failed media_id=%s", item.media_id)
            provenance["naming_refresh"] = {"status": "unavailable", "reason": "recognition_unavailable"}
            updates[item.media_id] = {"provenance": provenance}
    return updates
