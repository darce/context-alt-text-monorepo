import React from 'react';

import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from '../../../components/ui/dialog';
import { guidedCopy } from '../../guidedPrototype/publicGuideCopy';
import {
  formatGuidedSimilarity,
  GUIDED_MATCH_THRESHOLD,
  getGuidedPerson,
  guidedNameCoverage,
  namesDecided,
  type GuidedDemoState,
  type GuidedFace,
  type GuidedFacePosition,
  type GuidedNameChoice,
  type GuidedPersonKey,
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
  const facesByPerson = scenario.faces.reduce<Map<GuidedPersonKey, GuidedFace[]>>((groups, face) => {
    const matches = groups.get(face.matchedPersonKey) ?? [];
    matches.push(face);
    groups.set(face.matchedPersonKey, matches);
    return groups;
  }, new Map());

  return (
    <section id={GUIDED_FACE_SECTION_ID} className="acx-guided-face" aria-labelledby="guided-faces-title" tabIndex={-1}>
      <header className="acx-guided-face__header">
        <h2 id="guided-faces-title">{guidedCopy('step.names')}</h2>
        <p>{guidedCopy('names.intro')}</p>
        <p>{guidedCopy('names.assisted')}</p>
        <p>{guidedCopy('names.threshold', { threshold: formatGuidedSimilarity(GUIDED_MATCH_THRESHOLD) })}</p>
      </header>

      <div id="guided-section-identity" tabIndex={-1} className="acx-guided-face__cards">
        {[...facesByPerson.entries()].map(([personKey, faces]) => {
          const person = getGuidedPerson(scenario, personKey);
          const personCoverage = coverage.find((entry) => entry.key === person.key);
          if (personCoverage === undefined) {
            throw new Error(`Missing guided name coverage for ${person.key}.`);
          }
          const position = faces[0]?.position;
          if (position === undefined) {
            throw new Error(`Missing guided face position for ${person.key}.`);
          }

          return (
            <GuidedFaceMatchCard
              key={person.key}
              matches={faces.map((face) => {
                const photo = scenario.pressPhotos.find((candidate) => candidate.key === face.imageKey);
                if (photo === undefined) {
                  throw new Error(`Missing guided press photo for ${face.imageKey}.`);
                }
                return { face, mediaUrl: photo.src };
              })}
              person={person}
              coverage={personCoverage}
              choice={state.choices[position]}
              disabled={pending}
              onChoose={(choice, origin) => onChoose(position, choice, origin)}
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
            aria-modal="true"
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
