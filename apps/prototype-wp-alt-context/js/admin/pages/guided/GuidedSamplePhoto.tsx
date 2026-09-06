import React, { useState } from 'react';

export interface GuidedSamplePhotoProps {
  src: string;
  altText: string;
  currentAltText: string;
  credit: string;
}

export const GuidedSamplePhoto = ({
  src,
  altText,
  currentAltText,
  credit,
}: GuidedSamplePhotoProps): React.JSX.Element => {
  const [imageFailed, setImageFailed] = useState(false);
  const fallbackLabel = `Sample photo unavailable. ${altText}`;

  return (
    <figure className="acx-guided-page__media-card">
      {imageFailed ? (
        <div
          className="acx-guided-page__image-placeholder acx-guided-page__image-placeholder--fallback"
          role="img"
          aria-label={fallbackLabel}
        >
          <strong>Sample photo unavailable</strong>
          <span>{altText}</span>
        </div>
      ) : (
        <img className="acx-guided-page__image" src={src} alt={altText} onError={() => setImageFailed(true)} />
      )}
      <figcaption>
        <strong>The photo</strong>
        <span>Alt text on the page right now: {currentAltText}</span>
        <span>Photo credit: {credit}.</span>
        <span>AltContext found two faces in this photo. The next step shows the matches.</span>
      </figcaption>
    </figure>
  );
};

GuidedSamplePhoto.displayName = 'GuidedSamplePhoto';
