import React from 'react';

import { FaceThumbnail } from '../../../components/ui/FaceThumbnail';
import type { GuidedFaceMatch, GuidedIdentity } from '../../guidedPrototype/state';

export interface GuidedFaceMatchCardProps {
  faceMatch: GuidedFaceMatch;
  identity: GuidedIdentity;
  mediaUrl: string;
  hasUnsavedEdit: boolean;
  onConfirm: () => void;
  onLeaveUnnamed: () => void;
}

const decisionStatusLabel = (identity: GuidedIdentity, matchedPersonName: string): string => {
  if (identity.status === 'confirmed') {
    return `You confirmed: ${identity.name ?? matchedPersonName}.`;
  }

  if (identity.status === 'unidentified') {
    return 'You kept the person unnamed.';
  }

  return 'You have not decided yet.';
};

export const GuidedFaceMatchCard = ({
  faceMatch,
  identity,
  mediaUrl,
  hasUnsavedEdit,
  onConfirm,
  onLeaveUnnamed,
}: GuidedFaceMatchCardProps): React.JSX.Element => {
  const faceLabel = faceMatch.faceCount === 1 ? 'face' : 'faces';
  const identityChangeReasonId = 'guided-identity-change-reason';
  const confirmDisabled = hasUnsavedEdit || identity.status === 'confirmed';
  const leaveUnnamedDisabled = hasUnsavedEdit || identity.status === 'unidentified';

  return (
    <div id="guided-section-face" tabIndex={-1} aria-labelledby="guided-face-match-title" className="acx-guided-face">
      <div className="acx-guided-face__crop">
        <FaceThumbnail
          mediaUrl={mediaUrl}
          bbox={faceMatch.box}
          size="lg"
          shape="square"
          alt="Face found in the photo"
        />
      </div>
      <div className="acx-guided-face__content">
        <h3 id="guided-face-match-title">Face found in the photo</h3>
        <p>AltContext found {faceMatch.faceCount} {faceLabel}.</p>
        <p>
          It matches a person you named before: <strong>{faceMatch.matchedPersonName}</strong>.
        </p>
        <p className="acx-guided-face__strength">
          <span className="acx-guided-face__strength-icon" aria-hidden="true">
            ✓
          </span>{' '}
          Match strength: {faceMatch.strength}. This face is close to {faceMatch.similarPhotoCount} saved photos of{' '}
          {faceMatch.matchedPersonName}.
        </p>
        <div>
          <p>How this works</p>
          <ol aria-label="How this works">
            <li>AltContext finds faces in the photo.</li>
            <li>It compares each face to people you already named.</li>
            <li>It asks you to confirm. Nothing is named without your OK.</li>
          </ol>
        </div>
        <p className="acx-guided-face__disclosure">
          This match was saved from an earlier run. The demo does not run recognition live.
        </p>
        <p className="acx-guided-face__decision">{decisionStatusLabel(identity, faceMatch.matchedPersonName)}</p>
        <p id={identityChangeReasonId} className="acx-guided-face__change-note">
          Changing your answer swaps in a different saved draft. Save or discard your edit first.
        </p>
        <div
          id="guided-section-identity"
          tabIndex={-1}
          aria-label="Confirm the match"
          className="acx-guided-face__actions"
        >
          <button
            type="button"
            className="acx-button acx-button--secondary"
            onClick={onConfirm}
            disabled={confirmDisabled}
            aria-describedby={confirmDisabled ? identityChangeReasonId : undefined}
          >
            Yes, this is {faceMatch.matchedPersonName}
          </button>
          <button
            type="button"
            className="acx-button acx-button--tertiary"
            onClick={onLeaveUnnamed}
            disabled={leaveUnnamedDisabled}
            aria-describedby={leaveUnnamedDisabled ? identityChangeReasonId : undefined}
          >
            Keep the person unnamed
          </button>
        </div>
      </div>
    </div>
  );
};

GuidedFaceMatchCard.displayName = 'GuidedFaceMatchCard';
