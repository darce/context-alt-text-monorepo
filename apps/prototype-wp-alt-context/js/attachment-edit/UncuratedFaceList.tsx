/**
 * Right-pane uncurated face list for post.php attachment edit (UXP-5 slice 4).
 * FaceThumbnail crops + workbench deep links + list↔overlay cross-highlight.
 */

import * as React from 'react';

import type { BoundingBox } from '../admin/api/recognition/types/identity';
import {
  faceOverlayDomId,
  isCuratedFace,
  sanitizeDomIdToken,
  type FaceOverlayIdentity,
} from '../components/ui/FaceOverlayLayer';
import { isCompleteFiniteBbox } from '../components/ui/faceGeometry';
import { FaceThumbnail } from '../components/ui/FaceThumbnail';
import { ATTACHMENT_EDIT_COPY, unnamedFaceLabel } from './copy';

export interface UncuratedFaceListProps {
  identities: FaceOverlayIdentity[];
  mediaUrl: string;
  /** Plain workbench admin URL only — no invented media-filter params (E21-10). */
  workbenchUrl: string;
  highlightedFaceId?: string | null;
  onHighlightChange?: (faceId: string | null) => void;
}

type FaceWithBbox = FaceOverlayIdentity & { bbox: BoundingBox };

const compareBboxReadingOrder = (a: FaceWithBbox, b: FaceWithBbox): number => {
  const ay = a.bbox.y;
  const by = b.bbox.y;
  if (ay !== by) {
    return ay - by;
  }
  return a.bbox.x - b.bbox.x;
};

/** Uncurated faces with complete finite bboxes, sorted bbox.y then bbox.x (matches FaceOverlayLayer). */
export const selectUncuratedFacesInReadingOrder = (
  identities: FaceOverlayIdentity[],
): FaceWithBbox[] => {
  return identities
    .filter((id): id is FaceWithBbox => isCompleteFiniteBbox(id.bbox) && !isCuratedFace(id))
    .slice()
    .sort(compareBboxReadingOrder);
};

export const uncuratedListRowDomId = (faceId: string): string => {
  return `acx-uncurated-list-${sanitizeDomIdToken(faceId)}`;
};

export const UncuratedFaceList: React.FC<UncuratedFaceListProps> = ({
  identities,
  mediaUrl,
  workbenchUrl,
  highlightedFaceId = null,
  onHighlightChange,
}) => {
  const uncurated = React.useMemo(
    () => selectUncuratedFacesInReadingOrder(identities),
    [identities],
  );

  if (uncurated.length === 0) {
    return null;
  }

  const total = uncurated.length;

  return (
    <div
      className="acx-uncurated-face-list"
      data-testid="acx-uncurated-face-list"
    >
      <ul className="acx-uncurated-face-list__items">
        {uncurated.map((face, index) => {
          const faceNumber = index + 1;
          const label = unnamedFaceLabel(faceNumber, total);
          const rowId = uncuratedListRowDomId(face.identity_id);
          const overlayId = faceOverlayDomId(face.identity_id);
          const highlighted = highlightedFaceId === face.identity_id;

          return (
            <li
              key={face.identity_id}
              id={rowId}
              className={[
                'acx-uncurated-face-list__row',
                highlighted ? 'acx-uncurated-face-list__row--highlighted' : '',
              ]
                .filter(Boolean)
                .join(' ')}
              data-face-id={face.identity_id}
              data-highlighted={highlighted ? 'true' : 'false'}
              onMouseEnter={() => onHighlightChange?.(face.identity_id)}
              onMouseLeave={() => onHighlightChange?.(null)}
              onFocusCapture={() => onHighlightChange?.(face.identity_id)}
              onBlurCapture={(event) => {
                const next = event.relatedTarget;
                if (next instanceof Node && event.currentTarget.contains(next)) {
                  return;
                }
                onHighlightChange?.(null);
              }}
            >
              <FaceThumbnail
                mediaUrl={mediaUrl}
                bbox={face.bbox}
                size="sm"
                alt={label}
                className="acx-uncurated-face-list__thumb"
              />
              <span className="acx-uncurated-face-list__label">{label}</span>
              {workbenchUrl ? (
                <a
                  className="acx-uncurated-face-list__link"
                  href={workbenchUrl}
                  aria-controls={overlayId}
                  aria-describedby={overlayId}
                  data-testid={`acx-name-person-link-${face.identity_id}`}
                >
                  {ATTACHMENT_EDIT_COPY.nameThisPerson}
                </a>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
};

UncuratedFaceList.displayName = 'UncuratedFaceList';
