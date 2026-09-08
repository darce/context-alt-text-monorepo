import React from 'react';

import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from '../../../components/ui/dialog';
import { guidedCopy } from '../../guidedPrototype/copy';
import {
  getGuidedPerson,
  guidedNameCoverage,
  namesDecided,
  type GuidedDemoState,
  type GuidedFacePosition,
  type GuidedNameChoice,
  type GuidedScenario,
} from '../../guidedPrototype/state';
import { GUIDED_FACE_SECTION_ID } from './GuidedPrototypeGuide';
import { GuidedFaceMatchCard } from './GuidedFaceMatchCard';

export interface GuidedFacesPanelProps {
  scenario: GuidedScenario;
  state: GuidedDemoState;
  onChoose: (position: GuidedFacePosition, choice: GuidedNameChoice, origin: HTMLInputElement) => void;
  onContinue: () => void;
  onConfirmReplacement: () => void;
  onCancelReplacement: () => void;
}

export const GuidedFacesPanel = ({
  scenario,
  state,
  onChoose,
  onContinue,
  onConfirmReplacement,
  onCancelReplacement,
}: GuidedFacesPanelProps): React.JSX.Element => {
  const decided = namesDecided(state);
  const coverage = guidedNameCoverage(scenario);
  const pending = state.pendingChoiceChange !== null;

  return (
    <section id={GUIDED_FACE_SECTION_ID} className="acx-guided-face" aria-labelledby="guided-faces-title">
      <header className="acx-guided-face__header">
        <h2 id="guided-faces-title">{guidedCopy('step.names')}</h2>
        <p>{guidedCopy('names.intro')}</p>
        <p>{guidedCopy('names.assisted')}</p>
      </header>

      <div id="guided-section-identity" tabIndex={-1} className="acx-guided-face__cards">
        {scenario.faces.map((face) => {
          const person = getGuidedPerson(scenario, face.matchedPersonKey);
          const personCoverage = coverage.find((entry) => entry.key === person.key);
          if (personCoverage === undefined) {
            throw new Error(`Missing guided name coverage for ${person.key}.`);
          }

          return (
            <GuidedFaceMatchCard
              key={face.id}
              face={face}
              person={person}
              coverage={personCoverage}
              choice={state.choices[face.position]}
              mediaUrl={scenario.pressPhoto.src}
              disabled={pending}
              onChoose={(choice, origin) => onChoose(face.position, choice, origin)}
            />
          );
        })}
      </div>

      {decided ? null : <p className="acx-guided-face__next-reason">{guidedCopy('names.next_blocked')}</p>}
      <button type="button" className="acx-button acx-button--primary" onClick={onContinue} disabled={!decided}>
        {guidedCopy('names.next')}
      </button>

      <DialogRoot
        open={pending}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) {
            onCancelReplacement();
          }
        }}
      >
        <DialogPortal>
          <DialogOverlay />
          <DialogContent
            onCloseAutoFocus={(event) => {
              event.preventDefault();
            }}
          >
            <DialogTitle>{guidedCopy('names.change_title')}</DialogTitle>
            <DialogDescription>{guidedCopy('names.change_body')}</DialogDescription>
            <div className="acx-dialog__actions">
              <button type="button" className="acx-button acx-button--secondary" onClick={onCancelReplacement}>
                {guidedCopy('names.change_cancel')}
              </button>
              <button type="button" className="acx-button acx-button--primary" onClick={onConfirmReplacement}>
                {guidedCopy('names.change_confirm')}
              </button>
            </div>
          </DialogContent>
        </DialogPortal>
      </DialogRoot>
    </section>
  );
};

GuidedFacesPanel.displayName = 'GuidedFacesPanel';
