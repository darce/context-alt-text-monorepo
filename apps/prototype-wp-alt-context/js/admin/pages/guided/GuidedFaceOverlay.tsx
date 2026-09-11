import React, { useCallback, useRef, useState } from 'react';
import { AlertTriangle } from 'lucide-react';

import type { BoundingBox } from '../../api/recognition/types/identity';
import { isUsableNaturalSize, overlayRectFor } from '../../../components/ui/faceGeometry';
import { GUIDED_MATCH_STRENGTH, type GuidedMatchStrength } from '../../guidedPrototype/state';

export interface GuidedFaceOverlayFace {
  id: string;
  box: BoundingBox;
  label: string;
  similarityText: string;
  strength: GuidedMatchStrength;
}

export interface GuidedFaceOverlayProps {
  faces: GuidedFaceOverlayFace[];
  naturalSize: { width: number; height: number };
  /** Parent sets this on pointer-enter / focus-within of the figure for the CSS reveal state. */
  visible: boolean;
  /** Optional: the face currently focused via the chooser; renders emphasised. */
  highlightedFaceId?: string | null;
  onHighlightChange?: (faceId: string | null) => void;
  idPrefix: string;
}

const GUIDED_FACE_OVERLAY_TEST_ID = 'guided-face-overlay';
const GUIDED_FACE_OVERLAY_ID_SUFFIX = 'face-overlay';
const GUIDED_FACE_BUTTON_ID_SUFFIX = 'face';
const WEAK_MATCH_ICON_LABEL = 'Weak match';

const outlineStyle = (box: BoundingBox, naturalSize: GuidedFaceOverlayProps['naturalSize']): React.CSSProperties => {
  const rect = overlayRectFor(box, naturalSize);

  return {
    left: `${rect.left}%`,
    top: `${rect.top}%`,
    width: `${rect.width}%`,
    height: `${rect.height}%`,
  };
};

const faceButtonId = (idPrefix: string, faceId: string): string =>
  `${idPrefix}-${GUIDED_FACE_BUTTON_ID_SUFFIX}-${faceId}`;

const faceChipText = (face: GuidedFaceOverlayFace): string => `${face.label} · ${face.similarityText}`;

const faceAccessibleName = (face: GuidedFaceOverlayFace): string => `${face.label}, ${face.similarityText}`;

export const GuidedFaceOverlay: React.FC<GuidedFaceOverlayProps> = ({
  faces,
  naturalSize,
  visible,
  highlightedFaceId = null,
  onHighlightChange,
  idPrefix,
}) => {
  const [interactionFaceId, setInteractionFaceId] = useState<string | null>(null);
  const [pinnedFaceId, setPinnedFaceId] = useState<string | null>(null);
  const interactionFaceRef = useRef<string | null>(null);
  const pinnedFaceRef = useRef<string | null>(null);
  const reportedFaceRef = useRef<string | null>(null);

  const reportHighlight = useCallback(
    (faceId: string | null): void => {
      if (reportedFaceRef.current === faceId) {
        return;
      }
      reportedFaceRef.current = faceId;
      onHighlightChange?.(faceId);
    },
    [onHighlightChange],
  );

  const highlightFace = useCallback(
    (faceId: string): void => {
      interactionFaceRef.current = faceId;
      setInteractionFaceId(faceId);
      reportHighlight(faceId);
    },
    [reportHighlight],
  );

  const clearInteraction = useCallback(
    (faceId: string): void => {
      if (interactionFaceRef.current !== faceId) {
        return;
      }
      interactionFaceRef.current = null;
      setInteractionFaceId((current) => (current === faceId ? null : current));
      reportHighlight(pinnedFaceRef.current);
    },
    [reportHighlight],
  );

  const clearHighlight = useCallback((): void => {
    interactionFaceRef.current = null;
    pinnedFaceRef.current = null;
    setInteractionFaceId(null);
    setPinnedFaceId(null);
    reportedFaceRef.current = null;
    onHighlightChange?.(null);
    // Keep the active button in the tab sequence after Escape. The parent can
    // close the figure-level reveal while focus remains a useful anchor.
  }, [onHighlightChange]);

  const togglePinnedFace = useCallback(
    (faceId: string): void => {
      const nextPinnedFaceId = pinnedFaceRef.current === faceId ? null : faceId;
      pinnedFaceRef.current = nextPinnedFaceId;
      setPinnedFaceId(nextPinnedFaceId);
      reportHighlight(interactionFaceRef.current ?? nextPinnedFaceId);
    },
    [reportHighlight],
  );

  const usableNaturalSize = isUsableNaturalSize(naturalSize);
  const overlayId = `${idPrefix}-${GUIDED_FACE_OVERLAY_ID_SUFFIX}`;

  return (
    <div
      id={overlayId}
      className="acx-guided-face-overlay"
      data-testid={GUIDED_FACE_OVERLAY_TEST_ID}
      data-visible={visible ? 'true' : 'false'}
      data-natural-size-valid={usableNaturalSize ? 'true' : 'false'}
    >
      {faces.map((face) => {
        const isWeak = face.strength === GUIDED_MATCH_STRENGTH.WEAK;
        const isPinned = pinnedFaceId === face.id;
        const isHighlighted = highlightedFaceId === face.id || interactionFaceId === face.id || isPinned;
        const chipText = faceChipText(face);
        const accessibleName = faceAccessibleName(face);

        return (
          <button
            key={face.id}
            id={faceButtonId(idPrefix, face.id)}
            type="button"
            className={[
              'acx-guided-face-overlay__outline',
              isWeak ? 'acx-guided-face-overlay__outline--weak' : '',
              isHighlighted ? 'acx-guided-face-overlay__outline--highlighted' : '',
              isPinned ? 'acx-guided-face-overlay__outline--pinned' : '',
            ]
              .filter(Boolean)
              .join(' ')}
            style={outlineStyle(face.box, naturalSize)}
            aria-label={accessibleName}
            aria-pressed={isPinned}
            tabIndex={0}
            data-face-id={face.id}
            data-strength={face.strength}
            data-highlighted={isHighlighted ? 'true' : 'false'}
            data-pinned={isPinned ? 'true' : 'false'}
            onClick={() => {
              highlightFace(face.id);
              togglePinnedFace(face.id);
            }}
            onFocus={() => highlightFace(face.id)}
            onBlur={() => clearInteraction(face.id)}
            onPointerEnter={() => highlightFace(face.id)}
            onPointerLeave={() => clearInteraction(face.id)}
            onMouseEnter={() => highlightFace(face.id)}
            onMouseLeave={() => clearInteraction(face.id)}
            onKeyDown={(event) => {
              if (event.key !== 'Escape') {
                return;
              }
              event.preventDefault();
              clearHighlight();
            }}
          >
            <span
              className={['acx-guided-face-overlay__chip', isWeak ? 'acx-guided-face-overlay__chip--weak' : '']
                .filter(Boolean)
                .join(' ')}
            >
              {isWeak ? (
                <span className="acx-guided-face-overlay__warning-icon" role="img" aria-label={WEAK_MATCH_ICON_LABEL}>
                  <AlertTriangle aria-hidden="true" size={14} />
                </span>
              ) : null}
              <span className="acx-guided-face-overlay__chip-label">{chipText}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
};

GuidedFaceOverlay.displayName = 'GuidedFaceOverlay';
