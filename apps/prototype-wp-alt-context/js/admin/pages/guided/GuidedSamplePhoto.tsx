import React, { useState } from 'react';

import samplePhoto from '../../assets/guided/altcontext-sample.jpeg';

const SAMPLE_PHOTO_ALT =
  'Portrait photograph of a man with shoulder-length dark hair and a beard, wearing a grey jacket over a dark shirt, against a light background.';
const SAMPLE_PHOTO_FALLBACK_LABEL = `Sample photo unavailable. ${SAMPLE_PHOTO_ALT}`;

export interface GuidedSamplePhotoProps {
  mediaAltText: string;
  credit: string;
}

export const GuidedSamplePhoto = ({ mediaAltText, credit }: GuidedSamplePhotoProps): React.JSX.Element => {
  const [imageFailed, setImageFailed] = useState(false);

  return (
    <figure className="acx-guided-page__media-card">
      {imageFailed ? (
        <div
          className="acx-guided-page__image-placeholder acx-guided-page__image-placeholder--fallback"
          role="img"
          aria-label={SAMPLE_PHOTO_FALLBACK_LABEL}
        >
          <strong>Sample photo unavailable</strong>
          <span>{SAMPLE_PHOTO_ALT}</span>
        </div>
      ) : (
        <img
          className="acx-guided-page__image"
          src={samplePhoto}
          alt={SAMPLE_PHOTO_ALT}
          onError={() => setImageFailed(true)}
        />
      )}
      <figcaption>
        <strong>Original media · supplied sample photo</strong>
        <span>
          <strong>Current alt text on the page:</strong> {mediaAltText}
        </span>
        <span>Photo credit: {credit}.</span>
        <span>Identity evidence comes from the sample record; it was not inferred from the image.</span>
      </figcaption>
    </figure>
  );
};

GuidedSamplePhoto.displayName = 'GuidedSamplePhoto';
