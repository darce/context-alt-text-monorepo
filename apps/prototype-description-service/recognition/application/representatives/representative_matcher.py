"""Representative-based matching (order-independent)."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from uuid import UUID

import numpy as np

from db.models import MediaIdentity
from recognition.application.clustering.centroid_utils import compute_similarity
from recognition.application.clustering.cluster_validation import MemberValidationResult
from recognition.application.clustering.clustering_logger import (
    log_complete_link_check,
    log_rep_match,
    log_threshold_adjusted,
)
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
SuggestionValidationFn = Callable[[MediaIdentity, np.ndarray, UUID, float], Awaitable[MemberValidationResult]]
CreateSuggestionFn = Callable[[UUID, UUID, float, float], Awaitable[None]]


class RepresentativeMatcher:
    """Assign identities to clusters using representative embeddings (no centroid reliance).

    Optionally supports confidence-weighted adaptive thresholds (Option C) when
    settings.confidence_weighting_enabled is True.

    Supports suggestion tier for borderline matches when suggestion_validation and
    create_suggestion callbacks are provided.

    Early Stage Suggestion Guard:
    During early training (labeled_cluster_count < maturity_point), borderline matches
    that exceed the threshold but are below high_confidence_threshold create suggestions
    instead of auto-assigning. This prevents false positives when cluster representatives
    aren't yet stable.
    """

    def __init__(
        self,
        threshold: float,
        add_representative_embedding: AddRepFn,
        assign_to_cluster_by_id: AssignFn,
        borderline_validation: BorderlineValidationFn | None = None,
        settings: ClusteringSettings | None = None,
        suggestion_validation: SuggestionValidationFn | None = None,
        create_suggestion: CreateSuggestionFn | None = None,
        labeled_cluster_count: int = 0,
    ) -> None:
        self.threshold = threshold
        self._add_representative_embedding = add_representative_embedding
        self._assign_to_cluster_by_id = assign_to_cluster_by_id
        self._borderline_validation = borderline_validation
        self._settings = settings
        self._suggestion_validation = suggestion_validation
        self._create_suggestion = create_suggestion
        self._labeled_cluster_count = labeled_cluster_count

    def _is_early_stage(self) -> bool:
        """Check if we're in early training stage."""
        if not self._settings:
            return False
        return self._labeled_cluster_count < self._settings.adaptive_threshold_maturity_point

    def _compute_effective_threshold(self, identity: MediaIdentity) -> float:
        """Compute the effective threshold for this identity based on detection confidence.

        If confidence weighting is enabled, adjusts the base threshold based on
        detection quality (det_score and bbox size). High-quality detections get
        a lower threshold (easier to match), low-quality get higher (stricter).

        IMPORTANT: During early stage (few labeled clusters), confidence weighting
        is DISABLED to prevent false positives. We need to be stricter, not more
        lenient, when cluster representatives aren't stable yet.

        Returns:
            Effective threshold for this identity's matching.
        """
        if not self._settings or not self._settings.confidence_weighting_enabled:
            return self.threshold

        # CRITICAL: Disable confidence weighting during early stage
        # During early training, clusters are not stable and we should be stricter
        # to avoid false positive accumulation (snowball effect)
        if self._is_early_stage():
            logger.debug(
                "Confidence weighting DISABLED (early stage): identity=%s, using base threshold=%.3f",
                identity.id,
                self.threshold,
            )
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

    def _check_complete_link(
        self,
        identity_vector: np.ndarray,
        cluster_id: UUID,
        representatives_by_cluster: dict[UUID, list[np.ndarray]],
    ) -> tuple[bool, float, float, float]:
        """Check complete-link validation against ALL representatives of a cluster.

        Instead of just checking if ONE rep is similar enough, we check that:
        1. The MINIMUM similarity to any rep is above a floor (even the worst match is acceptable)
        2. The AVERAGE similarity across all reps is above a threshold

        This catches lookalikes who match one photo (e.g., same angle) but not others.

        Returns:
            (passed, min_similarity, avg_similarity, duration_ms)
        """
        start = time.perf_counter()
        if not self._settings:
            duration_ms = (time.perf_counter() - start) * 1000
            return True, 1.0, 1.0, duration_ms

        reps = representatives_by_cluster.get(cluster_id, [])
        if len(reps) < 2:
            # Not enough representatives for meaningful complete-link check
            duration_ms = (time.perf_counter() - start) * 1000
            return True, 1.0, 1.0, duration_ms

        similarities = [compute_similarity(identity_vector, rep) for rep in reps]
        min_sim = min(similarities)
        avg_sim = sum(similarities) / len(similarities)

        floor_passed = min_sim >= self._settings.complete_link_min_floor
        avg_passed = avg_sim >= self._settings.complete_link_avg_threshold

        passed = floor_passed and avg_passed
        duration_ms = (time.perf_counter() - start) * 1000

        logger.debug(
            "Complete-link check: cluster=%s, num_reps=%d, min_sim=%.4f (floor=%.4f, %s), "
            "avg_sim=%.4f (threshold=%.4f, %s), passed=%s",
            cluster_id,
            len(reps),
            min_sim,
            self._settings.complete_link_min_floor,
            "PASS" if floor_passed else "FAIL",
            avg_sim,
            self._settings.complete_link_avg_threshold,
            "PASS" if avg_passed else "FAIL",
            passed,
        )

        return passed, min_sim, avg_sim, duration_ms

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
            rep_count = len(representatives_by_cluster.get(best_cluster_id, [])) if best_cluster_id else 0

            # Use effective threshold (potentially adjusted by confidence weighting)
            effective_threshold = self._compute_effective_threshold(identity)

            if best_cluster_id and best_similarity >= effective_threshold:
                # Check if match is in borderline range (needs validation)
                # Use original threshold for borderline check to keep validation consistent
                is_borderline = borderline_upper is not None and best_similarity < borderline_upper

                # === Complete-Link Guard ===
                # Check that new face matches ALL representatives, not just the nearest one.
                # A lookalike might be 0.92 to one photo but 0.80 to another angle.
                complete_link_passed, min_sim, avg_sim, duration_ms = self._check_complete_link(
                    identity_vector,
                    best_cluster_id,
                    representatives_by_cluster,
                )
                if self._settings and rep_count >= 2:
                    log_complete_link_check(
                        tenant_id=identity.tenant_id,
                        identity_id=identity.id,
                        cluster_id=best_cluster_id,
                        min_similarity=min_sim,
                        avg_similarity=avg_sim,
                        passed=complete_link_passed,
                        num_reps=rep_count,
                        duration_ms=duration_ms,
                    )

                if not complete_link_passed:
                    # Complete-link failed - create suggestion instead of auto-assigning
                    if self._create_suggestion is not None:
                        logger.info(
                            "Rep match COMPLETE_LINK_SUGGESTION: identity=%s -> cluster=%s, "
                            "best_sim=%.4f but min_rep_sim=%.4f, avg_rep_sim=%.4f (creating suggestion)",
                            identity.id,
                            best_cluster_id,
                            best_similarity,
                            min_sim,
                            avg_sim,
                        )
                        await self._create_suggestion(
                            identity.id,
                            best_cluster_id,
                            best_similarity,
                            avg_sim,  # Use avg rep similarity as quality indicator
                        )
                        continue
                    else:
                        # No suggestion callback - reject the match entirely
                        logger.warning(
                            "Rep match REJECTED (complete-link): identity=%s, best_sim=%.4f, "
                            "min_rep_sim=%.4f, avg_rep_sim=%.4f",
                            identity.id,
                            best_similarity,
                            min_sim,
                            avg_sim,
                        )
                        still_unclustered.append(identity)
                        continue

                # === Immature Cluster Guard ===
                # Block ALL matches to immature clusters (single representative).
                #
                # Rationale: With only 1 representative, complete-link validation cannot run.
                # A single face embedding can match 20+ different people at 88-92% similarity
                # (the "Cam Grant domination" problem). Instead of creating wrong suggestions,
                # we send these identities to Chinese Whispers to form their own clusters.
                # Once clusters have ≥2 diverse representatives, the complete-link guard
                # provides structural validation that catches lookalikes.
                #
                # The user must manually assign ≥2 faces to a person before the system
                # will match new faces to that person. This is a cold-start requirement.
                is_immature_cluster = rep_count < 2

                if self._settings and self._settings.early_stage_suggestion_enabled and is_immature_cluster:
                    logger.info(
                        "Rep match IMMATURE_CLUSTER_BLOCKED: identity=%s, matched cluster=%s at %.4f "
                        "but cluster has only %d rep(s) - sending to Chinese Whispers instead",
                        identity.id,
                        best_cluster_id,
                        best_similarity,
                        rep_count,
                    )
                    still_unclustered.append(identity)
                    continue

                # Early stage (few labeled clusters) requires high confidence for auto-assignment
                if (
                    self._settings
                    and self._settings.early_stage_suggestion_enabled
                    and self._is_early_stage()
                    and self._create_suggestion is not None
                    and best_similarity < self._settings.early_stage_high_confidence_threshold
                ):
                    logger.info(
                        "Rep match EARLY_STAGE_SUGGESTION: identity=%s -> cluster=%s, "
                        "similarity=%.4f < high_confidence=%.4f (labeled_clusters=%d)",
                        identity.id,
                        best_cluster_id,
                        best_similarity,
                        self._settings.early_stage_high_confidence_threshold,
                        self._labeled_cluster_count,
                    )
                    await self._create_suggestion(
                        identity.id,
                        best_cluster_id,
                        best_similarity,
                        best_similarity,
                    )
                    continue

                # Use suggestion-aware validation if available
                if is_borderline and self._suggestion_validation is not None:
                    logger.info(
                        "Rep match BORDERLINE: identity=%s, similarity=%.4f, validating with suggestion tier...",
                        identity.id,
                        best_similarity,
                    )
                    validation_result = await self._suggestion_validation(
                        identity,
                        identity_vector,
                        best_cluster_id,
                        best_similarity,
                    )

                    if validation_result.should_accept:
                        logger.info(
                            "Rep match VALIDATED (accept): identity=%s, similarity=%.4f, avg_member=%.4f",
                            identity.id,
                            best_similarity,
                            validation_result.avg_member_similarity,
                        )
                        # Fall through to assignment below
                    elif validation_result.should_suggest and self._create_suggestion:
                        logger.info(
                            "Rep match SUGGESTION: identity=%s -> cluster=%s, similarity=%.4f, avg_member=%.4f",
                            identity.id,
                            best_cluster_id,
                            best_similarity,
                            validation_result.avg_member_similarity,
                        )
                        await self._create_suggestion(
                            identity.id,
                            best_cluster_id,
                            best_similarity,
                            validation_result.avg_member_similarity,
                        )
                        # Don't add to still_unclustered - identity has a pending suggestion
                        # and should not be processed by Chinese Whispers
                        continue
                    else:
                        logger.warning(
                            "Rep match REJECTED (validation failed): identity=%s, similarity=%.4f, avg_member=%.4f",
                            identity.id,
                            best_similarity,
                            validation_result.avg_member_similarity,
                        )
                        still_unclustered.append(identity)
                        continue

                # Fall back to legacy validation if suggestion validation not available
                elif is_borderline and self._borderline_validation is not None:
                    logger.info(
                        "Rep match BORDERLINE: identity=%s, similarity=%.4f, validating...",
                        identity.id,
                        best_similarity,
                    )
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
