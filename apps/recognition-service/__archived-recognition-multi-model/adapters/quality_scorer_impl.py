"""
Quality Scorer Implementation
Concrete implementation of quality scoring for AdaFace quality-adaptive margin.
"""
import logging
from typing import Optional
import numpy as np
import cv2
from scipy.ndimage import gaussian_filter

from ..domain import QualityScorer

logger = logging.getLogger(__name__)


class QualityScorerImpl(QualityScorer):
    """
    Quality scoring for AdaFace embeddings (cf. AdaFace §3.2).
    - Primary metric: feature norm (‖embedding‖)
    - Optional: sharpness, brightness, contrast, occlusion
    - Calibration: Use collection-wide mean/std for norm normalization.
    """

    def __init__(self, norm_mean: float = 30.0, norm_std: float = 8.0, use_photometric: bool = False, use_occlusion: bool = False):
        """
        Args:
            norm_mean: Calibrated mean of embedding norm (for standardization).
            norm_std: Calibrated std of embedding norm (for standardization).
            use_photometric: If True, blend photometric quality cues.
            use_occlusion: If True, blend occlusion detection cue.
        """
        self.norm_mean = norm_mean     # <<<< NEW: norm calibration parameter
        self.norm_std = norm_std       # <<<< NEW: norm calibration parameter
        self.use_photometric = use_photometric  # <<<< NEW: toggle for photo features
        self.use_occlusion = use_occlusion      # <<<< NEW: toggle for occlusion
        logger.info("✅ Quality scorer (AdaFace) initialized (mean=%.2f, std=%.2f)", norm_mean, norm_std)

    def calculate_quality(self, face_image: np.ndarray, embedding: Optional[np.ndarray] = None) -> float:
        """
        Calculate quality score for a face image (AdaFace norm-based).
        Args:
            face_image: aligned face image (HWC, uint8)
            embedding: embedding (required)
        Returns:
            quality: float in [0, 1]
        """
        try:
            # 1. AdaFace feature-norm (main signal)
            if embedding is None:
                raise ValueError("Embedding required for AdaFace quality scoring.")   # <<<< CHANGED: error if embedding missing
            emb_norm = np.linalg.norm(embedding)
            norm_z = (emb_norm - self.norm_mean) / (self.norm_std + 1e-6)            # <<<< NEW: norm normalization (AdaFace style)
            q_norm = np.clip((norm_z + 3) / 6, 0.0, 1.0)                             # <<<< NEW: scales -3..3 to 0..1

            # 2. Optional: photometric fusion (legacy)
            q_photo = 1.0
            if self.use_photometric:                                                 # <<<< NEW: Only runs if enabled
                gray = face_image if face_image.ndim == 2 else cv2.cvtColor(face_image, cv2.COLOR_RGB2GRAY)
                sharp = self._calculate_sharpness(gray)
                bright = self._calculate_brightness(gray)
                contrast = self._calculate_contrast(gray)
                q_photo = 0.5 * sharp + 0.25 * bright + 0.25 * contrast              # <<<< NEW: weights updated, less dominant

            # 3. Optional: occlusion fusion
            q_occ = 1.0
            if self.use_occlusion:                                                   # <<<< NEW: Only runs if enabled
                q_occ = self._detect_occlusions(face_image)

            # 4. Weighted fusion (AdaFace norm dominates)
            if self.use_photometric and self.use_occlusion:                          # <<<< NEW: updated fusion logic
                quality = 0.7 * q_norm + 0.2 * q_photo + 0.1 * q_occ
            elif self.use_photometric:
                quality = 0.8 * q_norm + 0.2 * q_photo
            elif self.use_occlusion:
                quality = 0.9 * q_norm + 0.1 * q_occ
            else:
                quality = q_norm                                                     # <<<< NEW: norm-only default

            quality = float(np.clip(quality, 0.0, 1.0))
            logger.debug(f"Quality: {quality:.3f} (norm={q_norm:.3f}, photo={q_photo:.3f}, occ={q_occ:.3f})")
            return quality
        except Exception as e:
            logger.error(f"Quality calculation failed: {e}")
            return 0.5

    # Photometric and occlusion helpers below remain essentially the same but are now optional,
    # and their weights are reduced in the final quality score. No more embedding sparsity or legacy scoring.

    def _calculate_sharpness(self, gray: np.ndarray) -> float:
        try:
            var_lap = cv2.Laplacian(gray, cv2.CV_64F).var()
            return float(np.clip(var_lap / 100.0, 0, 1))
        except Exception as e:
            logger.warning(f"Sharpness calculation failed: {e}")
            return 0.5

    def _calculate_brightness(self, gray: np.ndarray) -> float:
        try:
            mean = np.mean(gray)
            return float(np.clip((mean - 50) / 150.0, 0, 1))
        except Exception as e:
            logger.warning(f"Brightness calculation failed: {e}")
            return 0.5

    def _calculate_contrast(self, gray: np.ndarray) -> float:
        try:
            std = np.std(gray)
            return float(np.clip(std / 64.0, 0, 1))
        except Exception as e:
            logger.warning(f"Contrast calculation failed: {e}")
            return 0.5

    def _detect_occlusions(self, img: np.ndarray) -> float:
        try:
            gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            grad_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
            grad_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
            grad_mag = np.sqrt(grad_x**2 + grad_y**2)
            mean_grad = np.mean(grad_mag)
            return float(np.clip(mean_grad / 50.0, 0, 1))
        except Exception as e:
            logger.warning(f"Occlusion calculation failed: {e}")
            return 0.8  # assume minimal occlusion on error
