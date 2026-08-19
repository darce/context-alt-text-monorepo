/**
 * Presentational face overlay layer for post.php attachment edit.
 * Positions curated chips and uncurated markers over a natural-size image.
 */

import * as React from 'react';
import { __, sprintf } from '@wordpress/i18n';
import { User, UserRound } from 'lucide-react';

import type { BoundingBox } from '../../admin/api/recognition/types/identity';
import { isHumanLabeledTarget } from '../../admin/pages/workbench/identity-clusters/suggestionProjection';
import {
  isCompleteFiniteBbox,
  isUsableNaturalSize,
  overlayRectFor,
  type NaturalSize,
} from './faceGeometry';

export interface FaceOverlayIdentity {
  identity_id: string;
  bbox: BoundingBox | null;
  cluster_label?: string | null;
  is_auto_label?: boolean;
}

export interface FaceOverlayLayerProps {
  identities: FaceOverlayIdentity[];
  naturalSize: NaturalSize;
  onActivate?: (faceId: string) => void;
  highlightedFaceId?: string | null;
  onHighlightChange?: (faceId: string | null) => void;
  /** Face currently under review — rendered as a "?" chip, not a name/marker. */
  reviewFaceId?: string | null;
}

/**
 * curated = human-shaped label ∧ not auto-label (AIPX-07 / E21-15-BR-27).
 * Auto-shape `cluster-*` labels never become curated chips even when the
 * backend omits/misflags `is_auto_label`.
 */
export function isCuratedFace(identity: FaceOverlayIdentity): boolean {
  return (
    identity.is_auto_label === false && isHumanLabeledTarget(identity.cluster_label)
  );
}

function compareBboxReadingOrder(a: FaceOverlayIdentity, b: FaceOverlayIdentity): number {
  const ay = a.bbox?.y ?? 0;
  const by = b.bbox?.y ?? 0;
  if (ay !== by) {
    return ay - by;
  }
  const ax = a.bbox?.x ?? 0;
  const bx = b.bbox?.x ?? 0;
  return ax - bx;
}

/** Allowlist for HTML id fragments: letters, digits, underscore, hyphen. */
const DOM_ID_SAFE = /^[A-Za-z0-9_-]+$/;

/**
 * Map arbitrary identity_id into a selector-safe, unique DOM id fragment.
 * Safe ids pass through; hostile chars hash to a stable `h…` token.
 */
export function sanitizeDomIdToken(raw: string): string {
  if (typeof raw === 'string' && raw.length > 0 && DOM_ID_SAFE.test(raw)) {
    return raw;
  }
  const source = typeof raw === 'string' ? raw : String(raw ?? '');
  // FNV-1a 32-bit — deterministic, no crypto dependency, unique for distinct inputs.
  let hash = 0x811c9dc5;
  for (let i = 0; i < source.length; i += 1) {
    hash ^= source.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return `h${(hash >>> 0).toString(36)}`;
}

export function faceOverlayDomId(faceId: string): string {
  return `acx-face-overlay-${sanitizeDomIdToken(faceId)}`;
}

function reviewAccessibleName(identity: FaceOverlayIdentity): string {
  if (isHumanLabeledTarget(identity.cluster_label) && identity.cluster_label) {
    return sprintf(
      /* translators: %s: person name on the face currently under review */
      __('Face under review: %s', 'alt-context'),
      identity.cluster_label,
    );
  }
  return __('Face under review', 'alt-context');
}

function outlineStyle(bbox: BoundingBox, naturalSize: NaturalSize): React.CSSProperties {
  const rect = overlayRectFor(bbox, naturalSize);
  return {
    left: `${rect.left}%`,
    top: `${rect.top}%`,
    width: `${rect.width}%`,
    height: `${rect.height}%`,
  };
}

function controlStyle(bbox: BoundingBox, naturalSize: NaturalSize): React.CSSProperties {
  const rect = overlayRectFor(bbox, naturalSize);
  // Center a ≥24×24 hit target on the bbox (A11Y-14).
  return {
    left: `${rect.left + rect.width / 2}%`,
    top: `${rect.top + rect.height / 2}%`,
  };
}

type FaceWithBbox = FaceOverlayIdentity & { bbox: BoundingBox };

export const FaceOverlayLayer: React.FC<FaceOverlayLayerProps> = ({
  identities,
  naturalSize,
  onActivate,
  highlightedFaceId = null,
  onHighlightChange,
  reviewFaceId = null,
}) => {
  // Local hover/focus so outline reveal works without waiting on a parent re-render.
  const [interactionFaceId, setInteractionFaceId] = React.useState<string | null>(null);

  const withBbox = React.useMemo(
    () => identities.filter((id): id is FaceWithBbox => isCompleteFiniteBbox(id.bbox)),
    [identities],
  );

  const isReviewFace = React.useCallback(
    (faceId: string): boolean => reviewFaceId != null && faceId === reviewFaceId,
    [reviewFaceId],
  );

  const reviewFaces = React.useMemo(
    () => withBbox.filter((face) => isReviewFace(face.identity_id)).slice().sort(compareBboxReadingOrder),
    [withBbox, isReviewFace],
  );

  const curated = React.useMemo(
    () =>
      withBbox
        .filter((face) => isCuratedFace(face) && !isReviewFace(face.identity_id))
        .slice()
        .sort(compareBboxReadingOrder),
    [withBbox, isReviewFace],
  );

  const uncurated = React.useMemo(
    () =>
      withBbox
        .filter((face) => !isCuratedFace(face) && !isReviewFace(face.identity_id))
        .slice()
        .sort(compareBboxReadingOrder),
    [withBbox, isReviewFace],
  );

  const uncuratedCount = uncurated.length;

  const handleEscBlur = React.useCallback((event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== 'Escape') {
      return;
    }
    event.preventDefault();
    event.currentTarget.blur();
  }, []);

  const handleEnter = React.useCallback(
    (faceId: string) => {
      setInteractionFaceId(faceId);
      onHighlightChange?.(faceId);
    },
    [onHighlightChange],
  );

  const handleLeave = React.useCallback(
    (faceId: string) => {
      setInteractionFaceId((current) => (current === faceId ? null : current));
      onHighlightChange?.(null);
    },
    [onHighlightChange],
  );

  const isOutlineRevealed = (faceId: string): boolean =>
    interactionFaceId === faceId || highlightedFaceId === faceId;

  const isHighlighted = (faceId: string): boolean =>
    highlightedFaceId === faceId || interactionFaceId === faceId;

  // Zero / non-finite natural size: empty layer shell (no NaN styles).
  if (!isUsableNaturalSize(naturalSize)) {
    return (
      <div
        className="acx-face-overlay"
        data-testid="acx-face-overlay-layer"
        data-empty-natural-size="true"
      />
    );
  }

  return (
    <div className="acx-face-overlay" data-testid="acx-face-overlay-layer">
      {/* Review chip first so the face under review is the first overlay tab stop. */}
      {reviewFaces.map((face) => {
        const highlighted = isHighlighted(face.identity_id);
        const accessibleName = reviewAccessibleName(face);
        return (
          <React.Fragment key={face.identity_id}>
            <div
              className={[
                'acx-face-overlay__outline',
                'acx-face-overlay__outline--halo',
                'acx-face-overlay__outline--review',
                'acx-face-overlay__outline--revealed',
                highlighted ? 'acx-face-overlay__outline--highlighted' : '',
              ]
                .filter(Boolean)
                .join(' ')}
              style={outlineStyle(face.bbox, naturalSize)}
              aria-hidden="true"
              data-face-id={face.identity_id}
            />
            <button
              type="button"
              id={faceOverlayDomId(face.identity_id)}
              className={[
                'acx-face-overlay__chip',
                'acx-face-overlay__chip--review',
                highlighted ? 'acx-face-overlay__chip--highlighted' : '',
              ]
                .filter(Boolean)
                .join(' ')}
              style={controlStyle(face.bbox, naturalSize)}
              aria-label={accessibleName}
              onClick={() => onActivate?.(face.identity_id)}
              onFocus={() => handleEnter(face.identity_id)}
              onBlur={() => handleLeave(face.identity_id)}
              onMouseEnter={() => handleEnter(face.identity_id)}
              onMouseLeave={() => handleLeave(face.identity_id)}
              onKeyDown={handleEscBlur}
            >
              <span className="acx-face-overlay__chip-glyph" aria-hidden="true">
                ?
              </span>
              <span className="acx-face-overlay__sr-only">{accessibleName}</span>
            </button>
          </React.Fragment>
        );
      })}

      {/* Curated chips first (bbox.y, bbox.x), then uncurated markers — DOM = focus order. */}
      {curated.map((face) => {
        const label = face.cluster_label ?? '';
        const highlighted = isHighlighted(face.identity_id);
        return (
          <React.Fragment key={face.identity_id}>
            <div
              className={[
                'acx-face-overlay__outline',
                'acx-face-overlay__outline--halo',
                'acx-face-overlay__outline--curated',
                highlighted ? 'acx-face-overlay__outline--highlighted' : '',
              ]
                .filter(Boolean)
                .join(' ')}
              style={outlineStyle(face.bbox, naturalSize)}
              aria-hidden="true"
              data-face-id={face.identity_id}
            />
            <button
              type="button"
              id={faceOverlayDomId(face.identity_id)}
              className={[
                'acx-face-overlay__chip',
                'acx-face-overlay__chip--curated',
                highlighted ? 'acx-face-overlay__chip--highlighted' : '',
              ]
                .filter(Boolean)
                .join(' ')}
              style={controlStyle(face.bbox, naturalSize)}
              aria-label={label}
              onClick={() => onActivate?.(face.identity_id)}
              onFocus={() => handleEnter(face.identity_id)}
              onBlur={() => handleLeave(face.identity_id)}
              onMouseEnter={() => handleEnter(face.identity_id)}
              onMouseLeave={() => handleLeave(face.identity_id)}
              onKeyDown={handleEscBlur}
            >
              <User size={14} className="acx-face-overlay__chip-icon" aria-hidden="true" />
              <span className="acx-face-overlay__chip-label">{label}</span>
            </button>
          </React.Fragment>
        );
      })}

      {uncurated.map((face, index) => {
        const faceNumber = index + 1;
        const accessibleName = sprintf(
          /* translators: 1: face index (1-based), 2: total uncurated faces */
          __('Unnamed face %1$d of %2$d', 'alt-context'),
          faceNumber,
          uncuratedCount,
        );
        const highlighted = isHighlighted(face.identity_id);
        const revealed = isOutlineRevealed(face.identity_id);
        const outlineClasses = [
          'acx-face-overlay__outline',
          'acx-face-overlay__outline--halo',
          'acx-face-overlay__outline--uncurated',
          highlighted ? 'acx-face-overlay__outline--highlighted' : '',
          revealed ? 'acx-face-overlay__outline--revealed' : '',
        ]
          .filter(Boolean)
          .join(' ');

        return (
          <React.Fragment key={face.identity_id}>
            <div
              className={outlineClasses}
              style={outlineStyle(face.bbox, naturalSize)}
              aria-hidden="true"
              data-face-id={face.identity_id}
              data-revealed={revealed ? 'true' : 'false'}
            />
            <button
              type="button"
              id={faceOverlayDomId(face.identity_id)}
              className={[
                'acx-face-overlay__marker',
                'acx-face-overlay__marker--uncurated',
                highlighted ? 'acx-face-overlay__marker--highlighted' : '',
              ]
                .filter(Boolean)
                .join(' ')}
              style={controlStyle(face.bbox, naturalSize)}
              aria-label={accessibleName}
              onClick={() => onActivate?.(face.identity_id)}
              onFocus={() => handleEnter(face.identity_id)}
              onBlur={() => handleLeave(face.identity_id)}
              onMouseEnter={() => handleEnter(face.identity_id)}
              onMouseLeave={() => handleLeave(face.identity_id)}
              onKeyDown={handleEscBlur}
            >
              <UserRound size={14} className="acx-face-overlay__marker-icon" aria-hidden="true" />
              <span className="acx-face-overlay__marker-label acx-face-overlay__sr-only">{accessibleName}</span>
            </button>
          </React.Fragment>
        );
      })}
    </div>
  );
};

FaceOverlayLayer.displayName = 'FaceOverlayLayer';
