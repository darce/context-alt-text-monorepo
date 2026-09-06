import React from 'react';

import { FaceThumbnail } from '../../../components/ui/FaceThumbnail';
import { GUIDED_IDENTITY_STATUS } from '../../guidedPrototype/state';
import type { GuidedFace, GuidedIdentity, GuidedLabeledPerson } from '../../guidedPrototype/state';

export interface GuidedFaceMatchCardProps {
  face: GuidedFace;
  person: GuidedLabeledPerson;
  identity: GuidedIdentity;
  mediaUrl: string;
}

const decisionStatusLabel = (identity: GuidedIdentity, personName: string): string => {
  if (identity.status === GUIDED_IDENTITY_STATUS.CONFIRMED) {
    return `You confirmed: ${personName}.`;
  }

  if (identity.status === GUIDED_IDENTITY_STATUS.UNIDENTIFIED) {
    return 'You kept this person unnamed.';
  }

  return 'You have not decided yet.';
};

export const GuidedFaceMatchCard = ({
  face,
  person,
  identity,
  mediaUrl,
}: GuidedFaceMatchCardProps): React.JSX.Element => {
  const faceTitleId = `guided-face-${face.id}-title`;

  return (
    <article aria-labelledby={faceTitleId} className="acx-guided-face__card">
      <div className="acx-guided-face__crop">
        <FaceThumbnail
          mediaUrl={mediaUrl}
          bbox={{
            x: face.box.x,
            y: face.box.y,
            width: face.box.width,
            height: face.box.height,
          }}
          size="lg"
          shape="square"
          alt={`Face on the ${face.position}`}
        />
      </div>
      <div className="acx-guided-face__content">
        <h4 id={faceTitleId}>Face on the {face.position}</h4>
        <p>
          It matches a person you named before: <strong>{person.name}</strong>.
        </p>
        <p className="acx-guided-face__strength">
          <span className="acx-guided-face__strength-icon" aria-hidden="true">
            ✓
          </span>{' '}
          Match strength: {face.strength}. This face is close to the {person.savedPhotoCount} saved photos of{' '}
          {person.name}.
        </p>

        {face.note ? <p className="acx-guided-face__note">{face.note}</p> : null}

        <div>
          <ul className="acx-guided-face__gallery" aria-label={`Saved photos of ${person.name}`}>
            {person.galleryPhotos.map((photo) => (
              <li key={photo.src}>
                <img src={photo.src} alt={photo.altText} loading="lazy" />
                <span className="screen-reader-text">{photo.credit}</span>
              </li>
            ))}
          </ul>
          <p className="acx-guided-face__gallery-caption">
            Saved photos of {person.name}: {person.galleryPhotos.length} of {person.savedPhotoCount} shown.
          </p>
        </div>

        <p className="acx-guided-face__decision">{decisionStatusLabel(identity, person.name)}</p>
      </div>
    </article>
  );
};

GuidedFaceMatchCard.displayName = 'GuidedFaceMatchCard';
