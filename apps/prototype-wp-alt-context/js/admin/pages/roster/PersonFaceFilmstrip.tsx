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
  onSelect: (faceId: string) => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLDivElement>) => void;
  railRef?: React.Ref<HTMLDivElement>;
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
  onKeyDown,
  railRef,
}: PersonFaceFilmstripProps): React.JSX.Element => {
  const activeId = selectedId ? rosterFaceDomId(selectedId) : undefined;

  return (
    <div
      ref={railRef}
      className="acx-roster__person-workspace-rail"
      role="listbox"
      aria-label={__('Face instances', 'alt-context')}
      aria-activedescendant={activeId}
      tabIndex={0}
      onKeyDown={onKeyDown}
    >
      {faces.map((face) => {
        const alt = sprintf(
          __('Instance %d for Cluster %d', 'alt-context'),
          face.mediaId,
          face.clusterIndex + 1,
        );
        const isSelected = face.identityId === selectedId;
        return (
          <button
            key={`${face.clusterId}-${face.identityId}-${face.mediaId}`}
            type="button"
            role="option"
            id={rosterFaceDomId(face.identityId)}
            className="acx-roster__person-workspace-rail-cell"
            aria-label={alt}
            aria-selected={isSelected}
            tabIndex={isSelected ? 0 : -1}
            onClick={() => onSelect(face.identityId)}
          >
            {renderRailMedia(face, alt)}
            <span className="acx-roster__person-workspace-rail-caption">
              {sprintf(__('Media %d', 'alt-context'), face.mediaId)}
            </span>
          </button>
        );
      })}
    </div>
  );
};
