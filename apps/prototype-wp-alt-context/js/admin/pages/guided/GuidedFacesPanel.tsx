import React from 'react';

import { guidedCopy } from '../../guidedPrototype/publicGuideCopy';
import {
  formatGuidedSimilarity,
  GUIDED_MATCH_THRESHOLD,
  namesDecided,
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
  /** @deprecated The replacement dialog is owned by RecordedWalkthrough. */
  onConfirmReplacement?: () => void;
  /** @deprecated The replacement dialog is owned by RecordedWalkthrough. */
  onCancelReplacement?: () => void;
}

export const GuidedFacesPanel = ({
  state,
  onContinue,
}: GuidedFacesPanelProps): React.JSX.Element => {
  const decided = namesDecided(state);

  return (
    <section id={GUIDED_FACE_SECTION_ID} className="acx-guided-face" aria-labelledby="guided-faces-title" tabIndex={-1}>
      <header className="acx-guided-face__header">
        <h2 id="guided-faces-title">{guidedCopy('step.names')}</h2>
        <p>{guidedCopy('names.intro')}</p>
        <p>{guidedCopy('names.assisted')}</p>
        <p>{guidedCopy('names.threshold', { threshold: formatGuidedSimilarity(GUIDED_MATCH_THRESHOLD) })}</p>
      </header>

      <div id="guided-section-identity" tabIndex={-1} className="acx-guided-face__cards" />

      {decided ? null : <p className="acx-guided-face__next-reason">{guidedCopy('names.next_blocked')}</p>}
      <button type="button" className="acx-button acx-button--primary" onClick={onContinue} disabled={!decided}>
        {guidedCopy('names.next')}
      </button>
    </section>
  );
};

GuidedFacesPanel.displayName = 'GuidedFacesPanel';
