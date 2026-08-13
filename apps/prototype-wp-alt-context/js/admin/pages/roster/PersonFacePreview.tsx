import React from 'react';
import { __ } from '@wordpress/i18n';

import { FaceThumbnail } from '../../../components/ui/FaceThumbnail';
import { isCroppableBbox } from '../../../components/ui/faceGeometry';
import type { BoundingBox } from '../../api/recognition/types/identity';
import { getSelectedFacePreviewLabel, type PersonScrubFace } from './personFaces';

const PREVIEW_SIZE_PX = 240;

interface PersonFacePreviewProps {
  face: PersonScrubFace | null;
  onOpenLightbox: (selection: { mediaUrl: string; bbox: BoundingBox; label: string }) => void;
}

export const PersonFacePreview = ({ face, onOpenLightbox }: PersonFacePreviewProps): React.JSX.Element => {
  if (!face) {
    return (
      <div className="acx-roster__person-workspace-preview">
        <p>{__('Select a face to preview.', 'alt-context')}</p>
      </div>
    );
  }

  const alt = getSelectedFacePreviewLabel(face);
  const mediaUrl = face.mediaUrl;
  const croppableBbox = isCroppableBbox(face.bbox) ? face.bbox : null;
  const canOpenLightbox = typeof mediaUrl === 'string' && mediaUrl.length > 0 && croppableBbox !== null;

  return (
    <div className="acx-roster__person-workspace-preview">
      {typeof mediaUrl === 'string' && mediaUrl.length > 0 && croppableBbox !== null ? (
        <FaceThumbnail
          mediaUrl={mediaUrl}
          bbox={croppableBbox}
          sizePx={PREVIEW_SIZE_PX}
          shape="square"
          alt={alt}
          loading="lazy"
        />
      ) : typeof mediaUrl === 'string' && mediaUrl.length > 0 ? (
        <img src={mediaUrl} alt={alt} width={PREVIEW_SIZE_PX} height={PREVIEW_SIZE_PX} loading="lazy" />
      ) : (
        <div role="img" aria-label={alt}>
          {__('No image', 'alt-context')}
        </div>
      )}
      {canOpenLightbox && typeof mediaUrl === 'string' && croppableBbox !== null ? (
        <button
          type="button"
          className="acx-button acx-button--secondary"
          onClick={() => onOpenLightbox({ mediaUrl, bbox: croppableBbox, label: alt })}
        >
          {__('Open original media', 'alt-context')}
        </button>
      ) : null}
    </div>
  );
};
