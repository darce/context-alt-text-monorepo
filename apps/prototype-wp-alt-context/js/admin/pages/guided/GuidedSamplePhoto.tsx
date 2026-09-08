import React, { useState } from 'react';

import { guidedCopy } from '../../guidedPrototype/copy';

export interface GuidedSamplePhotoProps {
  src: string;
  evidenceAlt: string;
  currentAltText: string;
  credit: string;
}

export const GuidedSamplePhoto = ({
  src,
  evidenceAlt,
  currentAltText,
  credit,
}: GuidedSamplePhotoProps): React.JSX.Element => {
  const [imageFailed, setImageFailed] = useState(false);

  return (
    <figure className="acx-guided-page__media-card">
      {imageFailed ? (
        <div
          className="acx-guided-page__image-placeholder acx-guided-page__image-placeholder--fallback"
          role="img"
          aria-label={evidenceAlt}
        >
          <span>{evidenceAlt}</span>
        </div>
      ) : (
        <img className="acx-guided-page__image" src={src} alt={evidenceAlt} onError={() => setImageFailed(true)} />
      )}
      <figcaption>
        <span>
          {guidedCopy('context.current_label')}: {currentAltText}
        </span>
        <span>{credit}</span>
      </figcaption>
    </figure>
  );
};

GuidedSamplePhoto.displayName = 'GuidedSamplePhoto';
