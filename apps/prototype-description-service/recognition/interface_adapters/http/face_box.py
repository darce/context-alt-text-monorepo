"""Shared face-box / representative response helpers for HTTP adapters."""

from __future__ import annotations

from recognition.domain.representative import ClusterRepresentative
from recognition.interface_adapters.http.blob_url import build_face_thumb_path
from recognition.interface_adapters.http.schemas.responses import FaceBoxResponse, RepresentativeResponse


def face_box_from_components(bbox_x, bbox_y, bbox_width, bbox_height) -> FaceBoxResponse | None:
    values = (bbox_x, bbox_y, bbox_width, bbox_height)
    if any(value is None for value in values):
        return None
    try:
        x, y, width, height = (int(value) for value in values)
    except (TypeError, ValueError):
        return None
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        return None
    return FaceBoxResponse(x=x, y=y, width=width, height=height)


def representative_response_from_domain(rep: ClusterRepresentative) -> RepresentativeResponse:
    rep_bbox = face_box_from_components(rep.bbox_x, rep.bbox_y, rep.bbox_width, rep.bbox_height)
    return RepresentativeResponse(
        id=str(rep.id),
        media_id=rep.media_id,
        thumb_url=(
            build_face_thumb_path(
                rep.media_url,
                x=rep_bbox.x,
                y=rep_bbox.y,
                width=rep_bbox.width,
                height=rep_bbox.height,
            )
            if rep_bbox is not None
            else None
        ),
        media_url=rep.media_url,
        bbox=rep_bbox,
        # Wire alias is is_user_selected; populate_by_name is off — pass alias kwarg.
        is_user_selected=rep.is_user_selected,
    )


__all__ = ["face_box_from_components", "representative_response_from_domain"]
