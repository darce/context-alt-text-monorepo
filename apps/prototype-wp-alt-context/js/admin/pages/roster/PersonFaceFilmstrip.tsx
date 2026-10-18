import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import { FaceThumbnail } from '../../../components/ui/FaceThumbnail';
import { isCroppableBbox } from '../../../components/ui/faceGeometry';
import { rosterFaceDomId } from './faceDomId';
import type { PersonScrubFace } from './personFaces';

const RAIL_THUMB_PX = 64;

interface PersonFaceFilmstripProps {
  faces: readonly PersonScrubFace[];
  selectedId: string | null;
  onSelect: (faceId: string, railFaceIds: readonly string[]) => void;
  railRef?: React.Ref<HTMLDivElement>;
  clusterOrdinal: number;
}

const renderRailMedia = (face: PersonScrubFace, alt: string): React.JSX.Element => {
  if (typeof face.mediaUrl === 'string' && face.mediaUrl.length > 0 && isCroppableBbox(face.bbox)) {
    return (
      <FaceThumbnail
        mediaUrl={face.mediaUrl}
        bbox={face.bbox}
        sizePx={RAIL_THUMB_PX}
        shape="square"
        alt={alt}
        loading="lazy"
      />
    );
  }

  if (typeof face.mediaUrl === 'string' && face.mediaUrl.length > 0) {
    return <img src={face.mediaUrl} alt={alt} width={RAIL_THUMB_PX} height={RAIL_THUMB_PX} loading="lazy" />;
  }

  return (
    <div role="img" aria-label={alt} style={{ width: RAIL_THUMB_PX, height: RAIL_THUMB_PX }}>
      {__('No image', 'alt-context')}
    </div>
  );
};

export const PersonFaceFilmstrip = ({
  faces,
  selectedId,
  onSelect,
  railRef,
  clusterOrdinal,
}: PersonFaceFilmstripProps): React.JSX.Element => {
  const visibleIds = faces.map((face) => face.faceId);
  const selectedInRail = selectedId !== null && visibleIds.includes(selectedId);
  const activeId = selectedInRail && selectedId ? rosterFaceDomId(selectedId) : undefined;

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>): void => {
    if (visibleIds.length === 0) {
      return;
    }

    const currentIndex = selectedInRail && selectedId ? visibleIds.indexOf(selectedId) : -1;
    let nextIndex = currentIndex;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
      nextIndex = Math.min(visibleIds.length - 1, currentIndex + 1);
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
      nextIndex = Math.max(0, currentIndex < 0 ? 0 : currentIndex - 1);
    } else if (event.key === 'Home') {
      nextIndex = 0;
    } else if (event.key === 'End') {
      nextIndex = visibleIds.length - 1;
    } else {
      return;
    }

    event.preventDefault();
    const nextId = visibleIds[nextIndex];
    if (nextId) {
      onSelect(nextId, visibleIds);
    }
  };

  return (
    <div
      ref={railRef}
      className="acx-roster__person-workspace-rail"
      role="listbox"
      aria-label={sprintf(__('Faces in face group %d', 'alt-context'), clusterOrdinal)}
      aria-orientation="horizontal"
      aria-activedescendant={activeId}
      tabIndex={0}
      onKeyDown={handleKeyDown}
    >
      {faces.map((face) => {
        const alt = sprintf(
          __('Face from media %d in face group %d', 'alt-context'),
          face.mediaId,
          face.clusterIndex + 1,
        );
        const isSelected = face.faceId === selectedId;
        return (
          <button
            key={face.faceId}
            type="button"
            role="option"
            id={rosterFaceDomId(face.faceId)}
            className="acx-roster__person-workspace-rail-cell"
            aria-label={alt}
            aria-selected={isSelected}
            tabIndex={-1}
            onClick={() => onSelect(face.faceId, visibleIds)}
          >
            {renderRailMedia(face, alt)}
            <span className="acx-roster__person-workspace-rail-caption">
              {sprintf(__('Media %d', 'alt-context'), face.mediaId)}
            </span>
            {isSelected ? (
              <span className="acx-roster__person-workspace-rail-selected" aria-hidden="true">
                {__('Selected', 'alt-context')}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
};
