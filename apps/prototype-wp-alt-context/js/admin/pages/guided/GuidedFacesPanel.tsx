import React from 'react';

import {
  getGuidedIdentity,
  getGuidedPerson,
  type GuidedPersonKey,
  type GuidedScenario,
} from '../../guidedPrototype/state';

import { GuidedFaceMatchCard } from './GuidedFaceMatchCard';

export interface GuidedFacesPanelProps {
  scenario: GuidedScenario;
  hasUnsavedEdit: boolean;
  onConfirm: (faceId: GuidedPersonKey) => void;
  onLeaveUnnamed: (faceId: GuidedPersonKey) => void;
}

const identityChangeReasonId = 'guided-identity-change-reason';

export const GuidedFacesPanel = ({
  scenario,
  hasUnsavedEdit,
  onConfirm,
  onLeaveUnnamed,
}: GuidedFacesPanelProps): React.JSX.Element => {
  return (
    <section
      id="guided-section-face"
      tabIndex={-1}
      aria-labelledby="guided-faces-title"
      className="acx-guided-face"
    >
      <header className="acx-guided-face__header">
        <h3 id="guided-faces-title">Faces found in the photo</h3>
        <p>AltContext found 2 faces. Each one matched a person you named before.</p>
      </header>

      <div className="acx-guided-face__how-it-works">
        <p>How this works</p>
        <ol aria-label="How this works">
          <li>AltContext finds every face in the photo.</li>
          <li>It compares each face to the people you already named.</li>
          <li>It asks you to confirm each match. Nothing is named without your OK.</li>
        </ol>
      </div>

      <p className="acx-guided-face__disclosure">
        These matches were saved from a real run. The demo does not run recognition live.
      </p>

      <div className="acx-guided-face__cards">
        {scenario.faces.map((face) => {
          const person = getGuidedPerson(scenario, face.matchedPersonKey);
          const identity = getGuidedIdentity(scenario, face.id);

          return (
            <GuidedFaceMatchCard
              key={face.id}
              face={face}
              person={person}
              identity={identity}
              mediaUrl={scenario.pressPhoto.src}
            />
          );
        })}
      </div>

      <div
        id="guided-section-identity"
        tabIndex={-1}
        aria-label="Confirm each match"
        className="acx-guided-face__decisions"
      >
        <h4>Confirm each match</h4>
        <p id={identityChangeReasonId} className="acx-guided-face__change-note">
          Changing an answer swaps in a different saved draft. Save or discard your edit first.
        </p>
        {scenario.faces.map((face) => {
          const person = getGuidedPerson(scenario, face.matchedPersonKey);
          const identity = getGuidedIdentity(scenario, face.id);
          const confirmDisabled = hasUnsavedEdit || identity.status === 'confirmed';
          const leaveUnnamedDisabled = hasUnsavedEdit || identity.status === 'unidentified';
          const describedBy = hasUnsavedEdit ? identityChangeReasonId : undefined;

          return (
            <div key={face.id} className="acx-guided-face__decision-row">
              <p>
                {person.name}, face on the {face.position}
              </p>
              <div className="acx-guided-face__decision-actions">
                <button
                  type="button"
                  className="acx-button acx-button--secondary"
                  onClick={() => onConfirm(face.id)}
                  disabled={confirmDisabled}
                  aria-describedby={describedBy}
                >
                  Yes, this is {person.name}
                </button>
                <button
                  type="button"
                  className="acx-button acx-button--tertiary"
                  onClick={() => onLeaveUnnamed(face.id)}
                  disabled={leaveUnnamedDisabled}
                  aria-describedby={describedBy}
                >
                  Keep this person unnamed
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
};

GuidedFacesPanel.displayName = 'GuidedFacesPanel';
