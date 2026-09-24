import React from 'react';

import { guidedCopy } from '../../guidedPrototype/publicGuideCopy';
import {
  bothNamesAnswered,
  GUIDED_IMAGE_KEYS,
  type GuidedDemoState,
  type GuidedFacePosition,
  type GuidedNameChoice,
  type GuidedScenario,
} from '../../guidedPrototype/state';
import { GUIDED_FACE_SECTION_ID } from './GuidedPrototypeGuide';

export interface GuidedFacesPanelProps {
  scenario: GuidedScenario;
  state: GuidedDemoState;
  onChoose: (position: GuidedFacePosition, choice: GuidedNameChoice, origin: HTMLInputElement) => void;
  onContinue: () => void;
}

export const GuidedFacesPanel = ({ state, onContinue }: GuidedFacesPanelProps): React.JSX.Element => {
  const decided = GUIDED_IMAGE_KEYS.every((imageKey) => bothNamesAnswered(state, imageKey));

  return (
    <section id={GUIDED_FACE_SECTION_ID} className="acx-guided-face" aria-labelledby="guided-faces-title" tabIndex={-1}>
      <header className="acx-guided-face__header">
        <h2 id="guided-faces-title">{guidedCopy('step.names')}</h2>
        <p>{guidedCopy('names.intro')}</p>
        <p>{guidedCopy('names.assisted')}</p>
      </header>

      <div id="guided-section-identity" tabIndex={-1}>
        {decided ? null : <p className="acx-guided-face__next-reason">{guidedCopy('names.next_blocked')}</p>}
        <button type="button" className="acx-button acx-button--primary" onClick={onContinue} disabled={!decided}>
          {guidedCopy('names.next')}
        </button>
      </div>
    </section>
  );
};

GuidedFacesPanel.displayName = 'GuidedFacesPanel';
