"""Representative-based matching (order-independent)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

import numpy as np

from db.models import MediaIdentity
from recognition.application.clustering.centroid_utils import compute_similarity
from recognition.application.clustering.clustering_logger import log_rep_match, log_threshold_adjusted
from recognition.application.clustering.clustering_settings import ClusteringSettings
from recognition.application.representatives.confidence_utils import (
    adaptive_threshold,
    compute_detection_confidence,
)
from recognition.domain.embeddings import prepare_embedding

logger = logging.getLogger(__name__)

AssignFn = Callable[[MediaIdentity, np.ndarray, UUID, float], Awaitable[None]]
AddRepFn = Callable[[UUID, MediaIdentity], Awaitable[np.ndarray | None]]
BorderlineValidationFn = Callable[[MediaIdentity, np.ndarray, UUID, float], Awaitable[bool]]


class RepresentativeMatcher:
    """Assign identities to clusters using representative embeddings (no centroid reliance).

    Optionally supports confidence-weighted adaptive thresholds (Option C) when
    settings.confidence_weighting_enabled is True.
    """

    def __init__(
        self,
        threshold: float,
        add_representative_embedding: AddRepFn,
        assign_to_cluster_by_id: AssignFn,
        borderline_validation: BorderlineValidationFn | None = None,
        settings: ClusteringSettings | None = None,
    ) -> None:
        self.threshold = threshold
        self._add_representative_embedding = add_representative_embedding
        self._assign_to_cluster_by_id = assign_to_cluster_by_id
        self._borderline_validation = borderline_validation
        self._settings = settings

    def _compute_effective_threshold(self, identity: MediaIdentity) -> float:
        """Compute the effective threshold for this identity based on detection confidence.

        If confidence weighting is enabled, adjusts the base threshold based on
        detection quality (det_score and bbox size). High-quality detections get
        a lower threshold (easier to match), low-quality get higher (stricter).

        Returns:
            Effective threshold for this identity's matching.
        """
        if not self._settings or not self._settings.confidence_weighting_enabled:
            return self.threshold

        # Compute detection confidence from identity attributes
        det_score = identity.confidence if identity.confidence is not None else 0.9
        bbox_area = (identity.bbox_width or 100) * (identity.bbox_height or 100)

        confidence = compute_detection_confidence(
            det_score=det_score,
            bbox_area=bbox_area,
            min_bbox_area=self._settings.min_bbox_area,
        )

        effective_threshold = adaptive_threshold(
            base_threshold=self.threshold,
            confidence=confidence,
            confidence_midpoint=self._settings.confidence_midpoint,
            threshold_max_adjustment=self._settings.threshold_max_adjustment,
        )

        logger.debug(
            "Confidence weighting: identity=%s, det_score=%.3f, bbox_area=%d, "
            "confidence=%.3f, base_threshold=%.3f, effective_threshold=%.3f",
            identity.id,
            det_score,
            bbox_area,
            confidence,
            self.threshold,
            effective_threshold,
        )

        # Structured logging for threshold adjustment (only when different from base)
        if abs(effective_threshold - self.threshold) > 0.001:
            log_threshold_adjusted(
                tenant_id=identity.tenant_id,
                identity_id=identity.id,
                base_threshold=self.threshold,
                effective_threshold=effective_threshold,
                confidence=confidence,
                det_score=det_score,
                bbox_area=bbox_area,
            )

        return effective_threshold

    def _find_best_rep_match(
        self,
        identity_vector: np.ndarray,
        representatives_by_cluster: dict[UUID, list[np.ndarray]],
    ) -> tuple[UUID | None, float]:
        best_cluster_id: UUID | None = None
        best_similarity = 0.0

        for cluster_id, reps in representatives_by_cluster.items():
            for rep_vec in reps:
                similarity = compute_similarity(identity_vector, rep_vec)
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_cluster_id = cluster_id

        return best_cluster_id, best_similarity

    def best_match(
        self,
        identity_vector: np.ndarray,
        representatives_by_cluster: dict[UUID, list[np.ndarray]],
    ) -> tuple[UUID | None, float]:
        """Expose best representative match (for diagnostics)."""

        return self._find_best_rep_match(identity_vector, representatives_by_cluster)

    def is_borderline_match(
        self,
        similarity: float,
        borderline_upper: float,
    ) -> bool:
        """Check if a similarity score is in the borderline range requiring validation."""
        return self.threshold <= similarity < borderline_upper

    async def match(
        self,
        candidates: list[MediaIdentity],
        representatives_by_cluster: dict[UUID, list[np.ndarray]],
        borderline_upper: float | None = None,
    ) -> tuple[int, list[MediaIdentity], dict[UUID, list[np.ndarray]]]:
        """
        Match candidates to clusters via representatives.

        Args:
            candidates: Identities to match
            representatives_by_cluster: Existing cluster representatives
            borderline_upper: Upper bound for borderline range (e.g., 0.7).
                            Matches between threshold and this value are considered borderline
                            and should be validated via callback if provided.
        """
        assigned_count = 0
        still_unclustered: list[MediaIdentity] = []

        for identity in candidates:
            identity_vector = prepare_embedding(identity.embedding)
            best_cluster_id, best_similarity = self._find_best_rep_match(
                identity_vector,
                representatives_by_cluster,
            )

            # Use effective threshold (potentially adjusted by confidence weighting)
            effective_threshold = self._compute_effective_threshold(identity)

            if best_cluster_id and best_similarity >= effective_threshold:
                # Check if match is in borderline range (needs validation)
                # Use original threshold for borderline check to keep validation consistent
                is_borderline = (
                    borderline_upper is not None
                    and best_similarity < borderline_upper
                    and self._borderline_validation is not None
                )

                # Validate borderline matches before assigning
                if is_borderline:
                    logger.info(
                        "Rep match BORDERLINE: identity=%s, similarity=%.4f, validating...",
                        identity.id,
                        best_similarity,
                    )
                    assert self._borderline_validation is not None  # type narrowing
                    validation_passed = await self._borderline_validation(
                        identity,
                        identity_vector,
                        best_cluster_id,
                        best_similarity,
                    )
                    if not validation_passed:
                        logger.warning(
                            "Rep match REJECTED (borderline validation failed): identity=%s, similarity=%.4f",
                            identity.id,
                            best_similarity,
                        )
                        still_unclustered.append(identity)
                        continue
                    logger.info(
                        "Rep match VALIDATED: identity=%s, similarity=%.4f",
                        identity.id,
                        best_similarity,
                    )

                logger.info(
                    "Rep match ACCEPT%s: identity=%s, similarity=%.4f >= threshold=%.4f%s, cluster=%s",
                    " (validated)" if is_borderline else "",
                    identity.id,
                    best_similarity,
                    effective_threshold,
                    f" (adjusted from {self.threshold:.4f})" if effective_threshold != self.threshold else "",
                    best_cluster_id,
                )
                # Structured logging: match accepted
                log_rep_match(
                    tenant_id=identity.tenant_id,
                    identity_id=identity.id,
                    cluster_id=best_cluster_id,
                    similarity=best_similarity,
                    threshold=effective_threshold,
                    accepted=True,
                    effective_threshold=effective_threshold if effective_threshold != self.threshold else None,
                    is_borderline=is_borderline,
                )
                await self._assign_to_cluster_by_id(identity, identity_vector, best_cluster_id, best_similarity)
                rep_embedding = await self._add_representative_embedding(best_cluster_id, identity)
                if rep_embedding is not None:
                    representatives_by_cluster.setdefault(best_cluster_id, []).append(rep_embedding)
                assigned_count += 1
            else:
                logger.debug(
                    "Rep match REJECT: identity=%s, similarity=%.4f < threshold=%.4f%s",
                    identity.id,
                    best_similarity,
                    effective_threshold,
                    f" (adjusted from {self.threshold:.4f})" if effective_threshold != self.threshold else "",
                )
                # Structured logging: match rejected
                log_rep_match(
                    tenant_id=identity.tenant_id,
                    identity_id=identity.id,
                    cluster_id=None,
                    similarity=best_similarity,
                    threshold=effective_threshold,
                    accepted=False,
                    effective_threshold=effective_threshold if effective_threshold != self.threshold else None,
                )
                still_unclustered.append(identity)

        return assigned_count, still_unclustered, representatives_by_cluster
