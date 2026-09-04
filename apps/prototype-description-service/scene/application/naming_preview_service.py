"""Identity naming preview: fuse confirmed names into a generic describe draft."""

from __future__ import annotations

import logging
import uuid

from scene.application.fusion.reconcile import (
    Attachment,
    AttachmentDecision,
    FactSource,
)
from scene.application.identity_merge import (
    NamingPolicy,
    NamingProvenance,
    NamingSkipReason,
    load_confirmed_faces,
    load_suppressed_roster_ids,
    merge_identities,
)
from scene.interface_adapters.http.schemas.responses import (
    InjectedName as InjectedNameModel,
)
from scene.interface_adapters.http.schemas.responses import (
    NamingProvenance as NamingProvenanceModel,
)

_logger = logging.getLogger(__name__)


def _image_dimensions(image_bytes: bytes) -> tuple[int, int] | None:
    from io import BytesIO

    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(BytesIO(image_bytes)) as img:
            return img.size
    except (UnidentifiedImageError, OSError):
        return None


def _provenance_model(provenance) -> NamingProvenanceModel:
    return NamingProvenanceModel(
        injected_names=[
            InjectedNameModel(
                name=n.name,
                cluster_id=str(n.cluster_id),
                roster_id=str(n.roster_id) if n.roster_id is not None else None,
                detection_confidence=n.detection_confidence,
            )
            for n in provenance.injected_names
        ],
        naming_allowed=provenance.naming_allowed,
        reason=str(provenance.reason) if provenance.reason is not None else None,
        mode=str(provenance.mode) if provenance.mode is not None else None,
    )


async def load_fusion_naming_inputs(
    *,
    session,
    tenant,
    tenant_uuid: uuid.UUID,
    media_id: int,
    image_bytes: bytes,
) -> tuple[list, NamingPolicy | None]:
    """Load detector faces + naming policy once for fusion Stage-2 and naming preview."""
    if session is None or tenant is None:
        return [], None
    dims = _image_dimensions(image_bytes)
    if dims is None:
        return [], None
    try:
        faces = await load_confirmed_faces(
            session,
            tenant_id=tenant_uuid,
            media_id=media_id,
            image_width=dims[0],
            image_height=dims[1],
        )
        policy = NamingPolicy(
            agreement_enabled=tenant.naming_agreement_enabled,
            suppressed_roster_ids=await load_suppressed_roster_ids(session, tenant_id=tenant_uuid),
        )
        return list(faces), policy
    except Exception:  # noqa: BLE001 - fusion degrades without faces; naming has its own guard
        _logger.exception("failed loading faces/policy for media_id=%s; fusion uses empty faces", media_id)
        return [], None


async def naming_preview(
    *,
    session,
    tenant,
    tenant_uuid: uuid.UUID,
    media_id: int,
    image_bytes: bytes,
    generic_draft: str,
    phrase_boxes,
    confirmed_faces=None,
    naming_policy: NamingPolicy | None = None,
) -> tuple[str, NamingProvenanceModel]:
    """Compute the named preview draft (E19-4a). Draft-only — never writes alt text.

    ``phrase_boxes`` are the caption-grounding boxes (S4) — adapter output on
    generation, restored from the persisted cache row on hits. Empty for
    adapters without grounding, where naming degrades to the positional
    fallback when eligible.

    When ``confirmed_faces`` / ``naming_policy`` are provided (shared with
    Stage-2 fusion), they are reused so faces are not double-loaded.
    """
    if session is None or tenant is None:
        return generic_draft, _provenance_model(
            NamingProvenance(naming_allowed=False, reason=NamingSkipReason.DB_UNAVAILABLE)
        )
    try:
        if confirmed_faces is None or naming_policy is None:
            dims = _image_dimensions(image_bytes)
            if dims is None:
                return generic_draft, _provenance_model(
                    NamingProvenance(naming_allowed=False, reason=NamingSkipReason.IMAGE_UNREADABLE)
                )
            faces = await load_confirmed_faces(
                session,
                tenant_id=tenant_uuid,
                media_id=media_id,
                image_width=dims[0],
                image_height=dims[1],
            )
            policy = NamingPolicy(
                agreement_enabled=tenant.naming_agreement_enabled,
                suppressed_roster_ids=await load_suppressed_roster_ids(session, tenant_id=tenant_uuid),
            )
        else:
            # Preloaded path: still require readable image for naming eligibility.
            if _image_dimensions(image_bytes) is None:
                return generic_draft, _provenance_model(
                    NamingProvenance(naming_allowed=False, reason=NamingSkipReason.IMAGE_UNREADABLE)
                )
            faces = confirmed_faces
            policy = naming_policy
        result = merge_identities(
            caption=generic_draft,
            phrase_boxes=list(phrase_boxes),
            confirmed_faces=faces,
            policy=policy,
        )
        return result.named_draft, _provenance_model(result.provenance)
    except Exception:  # noqa: BLE001 - preview must never break the core describe response
        _logger.exception("naming preview failed for media_id=%s; degrading to generic draft", media_id)
        return generic_draft, _provenance_model(
            NamingProvenance(naming_allowed=False, reason=NamingSkipReason.MERGE_ERROR)
        )


def faces_for_naming_preview(
    confirmed_faces: list,
    attachments: tuple[Attachment, ...],
    phrase_boxes,
) -> list:
    """HARM-02: keep Stage-3 positional naming consistent with Stage-2 drops.

    With no phrase boxes, ``merge_identities`` falls back to positional naming
    of every eligible face — including identities whose ContextPack fact
    Stage-2 just dropped, which would make ``named_draft`` contradict
    ``attachment_provenance``. Stage-2 is the single decision point: faces
    whose identity fact was dropped never reach the positional fallback.
    Grounded mode (boxes present) already mirrors Stage-2's own merge, so it
    is left untouched.
    """
    if phrase_boxes or not attachments or not confirmed_faces:
        return confirmed_faces
    # fact_id formats are canonical in reconcile._identity_fact_id:
    # "identity:cluster:<id>" / "identity:id:<id>" / "identity:<idx>:<name>".
    dropped: set[tuple[str, str]] = set()
    for a in attachments:
        if a.fact_source is FactSource.IDENTITY and a.decision is AttachmentDecision.DROPPED:
            parts = a.fact_id.split(":", 2)
            if len(parts) == 3 and parts[1] in ("cluster", "id"):
                dropped.add((parts[1], parts[2]))
    if not dropped:
        return confirmed_faces
    return [
        f
        for f in confirmed_faces
        if ("cluster", str(f.cluster_id)) not in dropped and ("id", str(f.identity_id)) not in dropped
    ]
