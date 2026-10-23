"""Append observations at the scan transaction seam; never rewrite evidence."""

from __future__ import annotations

import json
import uuid
from collections import Counter
from typing import Any

from db.models.identity import FaceObservation


def _key(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def bind_scan_observations(
    session: Any, tenant_id: uuid.UUID, attachment_id: int, old_rows: list, detections: list, writes: list
) -> None:
    """Reuse only bijectively identical measurements in this complete attachment scan.

    Duplicates abstain; missing producer evidence clears the current pointer.
    Namespace is measurement grouping only, explicitly NOT restore attestation.
    """
    incoming = Counter(_key(d.face_evidence.to_dict()) for d in detections if d.face_evidence)
    geometry_counts = Counter(d.bbox[:2] for d in detections)
    previous = []
    for row in old_rows:
        observation = getattr(row, "face_observation", None)
        if (
            observation is not None
            and observation.tenant_id == tenant_id
            and observation.attachment_id == attachment_id
        ):
            previous.append(observation)
    prior_counts = Counter(_key(o.evidence) for o in previous)
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, f"acx:unattested-face-measurements:v1:{tenant_id}")
    for row, detection in writes:
        evidence = detection.face_evidence
        row.face_observation = None
        row.face_observation_id = None
        if evidence is None:
            continue
        payload = evidence.to_dict()
        key = _key(payload)
        if incoming[key] != 1 or prior_counts[key] > 1 or geometry_counts[detection.bbox[:2]] != 1:
            continue
        candidates = [o for o in previous if _key(o.evidence) == key and o.identity_namespace_id == namespace]
        if prior_counts[key] == 1 and not candidates:
            continue
        if candidates:
            observation = candidates[0]
        else:
            observation = FaceObservation(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                identity_namespace_id=namespace,
                attachment_id=attachment_id,
                evidence=payload,
            )
            session.add(observation)
        row.face_observation = observation
        row.face_observation_id = observation.id
