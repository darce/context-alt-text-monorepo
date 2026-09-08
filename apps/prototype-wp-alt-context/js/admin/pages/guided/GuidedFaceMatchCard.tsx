import React from 'react';

import { FaceThumbnail } from '../../../components/ui/FaceThumbnail';
import { guidedCopy } from '../../guidedPrototype/copy';
import {
  GUIDED_NAME_CHOICE,
  type GuidedFace,
  type GuidedLabeledPerson,
  type GuidedNameChoice,
  type GuidedNameCoverage,
} from '../../guidedPrototype/state';

export interface GuidedFaceMatchCardProps {
  face: GuidedFace;
  person: GuidedLabeledPerson;
  coverage: GuidedNameCoverage;
  choice: GuidedNameChoice;
  mediaUrl: string;
  disabled: boolean;
  onChoose: (choice: GuidedNameChoice, origin: HTMLInputElement) => void;
}

const choiceStatus = (choice: GuidedNameChoice, personName: string): string => {
  switch (choice) {
    case GUIDED_NAME_CHOICE.INCLUDE:
      return guidedCopy('names.included', { name: personName });
    case GUIDED_NAME_CHOICE.OMIT:
      return guidedCopy('names.omitted');
    case GUIDED_NAME_CHOICE.UNDECIDED:
      return guidedCopy('names.pending');
    default: {
      const exhaustive: never = choice;
      return exhaustive;
    }
  }
};

const coverageCopy = (coverage: GuidedNameCoverage): string =>
  coverage.shown === coverage.total
    ? guidedCopy('names.coverage_all', { total: coverage.total })
    : guidedCopy('names.coverage_partial', { shown: coverage.shown, total: coverage.total });

export const GuidedFaceMatchCard = ({
  face,
  person,
  coverage,
  choice,
  mediaUrl,
  disabled,
  onChoose,
}: GuidedFaceMatchCardProps): React.JSX.Element => {
  const titleId = `guided-face-${face.id}-title`;
  const groupName = `guided-name-${face.position}`;
  const includeId = `${groupName}-include`;
  const omitId = `${groupName}-omit`;

  const handleChange = (event: React.ChangeEvent<HTMLInputElement>, nextChoice: GuidedNameChoice): void => {
    onChoose(nextChoice, event.currentTarget);
  };

  return (
    <article aria-labelledby={titleId} className="acx-guided-face__card">
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
          alt=""
        />
      </div>
      <div className="acx-guided-face__content">
        <h3 id={titleId}>{guidedCopy('names.suggestion', { name: person.name })}</h3>

        <details className="acx-guided-face__evidence">
          <summary>{guidedCopy('names.evidence_open', { position: face.position })}</summary>
          <ul className="acx-guided-face__gallery" aria-label={person.name}>
            {person.galleryPhotos.map((photo) => (
              <li key={photo.src}>
                <img src={photo.src} alt={photo.altText} loading="lazy" />
                <span className="screen-reader-text">{photo.credit}</span>
              </li>
            ))}
          </ul>
          <p className="acx-guided-face__gallery-caption">{coverageCopy(coverage)}</p>
        </details>

        <fieldset data-testid={`name-choice-${face.position}`} disabled={disabled} className="acx-guided-face__choice">
          <legend>{guidedCopy('names.legend', { position: face.position })}</legend>
          <div className="acx-guided-face__choice-options">
            <label htmlFor={includeId}>
              <input
                id={includeId}
                type="radio"
                name={groupName}
                value={GUIDED_NAME_CHOICE.INCLUDE}
                checked={choice === GUIDED_NAME_CHOICE.INCLUDE}
                onChange={(event) => handleChange(event, GUIDED_NAME_CHOICE.INCLUDE)}
              />
              {guidedCopy('names.include', { name: person.name })}
            </label>
            <label htmlFor={omitId}>
              <input
                id={omitId}
                type="radio"
                name={groupName}
                value={GUIDED_NAME_CHOICE.OMIT}
                checked={choice === GUIDED_NAME_CHOICE.OMIT}
                onChange={(event) => handleChange(event, GUIDED_NAME_CHOICE.OMIT)}
              />
              {guidedCopy('names.omit')}
            </label>
          </div>
        </fieldset>

        <p className="acx-guided-face__decision">{choiceStatus(choice, person.name)}</p>
      </div>
    </article>
  );
};

GuidedFaceMatchCard.displayName = 'GuidedFaceMatchCard';
