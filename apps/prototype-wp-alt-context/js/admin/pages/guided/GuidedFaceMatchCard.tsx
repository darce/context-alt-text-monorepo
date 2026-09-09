import React, { useEffect, useRef, useState } from 'react';

import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from '../../../components/ui/dialog';
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

const INLINE_CROP_PX = 80;
const ENLARGED_CROP_PX = 240;

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

const cropAlt = (position: GuidedFace['position']): string => guidedCopy('names.crop_alt', { position });

export const GuidedFaceMatchCard = ({
  face,
  person,
  coverage,
  choice,
  mediaUrl,
  disabled,
  onChoose,
}: GuidedFaceMatchCardProps): React.JSX.Element => {
  const [comparisonOpen, setComparisonOpen] = useState(false);
  const enlargeRef = useRef<HTMLButtonElement>(null);
  const wasComparisonOpenRef = useRef(false);
  const titleId = `guided-face-${face.id}-title`;
  const groupName = `guided-name-${face.position}`;
  const includeId = `${groupName}-include`;
  const omitId = `${groupName}-omit`;
  const enlargeId = `${groupName}-enlarge`;
  const detectedAlt = cropAlt(face.position);

  useEffect(() => {
    if (comparisonOpen) {
      wasComparisonOpenRef.current = true;
      return;
    }
    if (!wasComparisonOpenRef.current) {
      return;
    }
    wasComparisonOpenRef.current = false;
    enlargeRef.current?.focus();
  }, [comparisonOpen]);

  const handleChange = (event: React.ChangeEvent<HTMLInputElement>, nextChoice: GuidedNameChoice): void => {
    onChoose(nextChoice, event.currentTarget);
  };

  const thumbnail = (sizePx = INLINE_CROP_PX): React.JSX.Element => (
    <FaceThumbnail
      mediaUrl={mediaUrl}
      bbox={{
        x: face.box.x,
        y: face.box.y,
        width: face.box.width,
        height: face.box.height,
      }}
      size="lg"
      sizePx={sizePx}
      shape="square"
      alt={detectedAlt}
    />
  );

  return (
    <article aria-labelledby={titleId} className="acx-guided-face__card">
      <div className="acx-guided-face__crop">
        {thumbnail()}
        <button
          ref={enlargeRef}
          id={enlargeId}
          type="button"
          className="acx-button acx-button--tertiary acx-guided-face__enlarge"
          onClick={() => setComparisonOpen(true)}
        >
          {guidedCopy('names.enlarge')}
        </button>
      </div>
      <div className="acx-guided-face__content">
        <h3 id={titleId}>{guidedCopy('names.suggestion', { name: person.name })}</h3>

        <details className="acx-guided-face__evidence" open>
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

      <DialogRoot open={comparisonOpen} onOpenChange={setComparisonOpen}>
        <DialogPortal>
          <DialogOverlay />
          <DialogContent
            aria-modal="true"
            className="acx-guided-face__lightbox"
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              enlargeRef.current?.focus();
            }}
          >
            <DialogTitle>{guidedCopy('names.enlarge_title')}</DialogTitle>
            <DialogDescription>{guidedCopy('names.evidence_open', { position: face.position })}</DialogDescription>
            <div className="acx-guided-face__lightbox-crop">{thumbnail(ENLARGED_CROP_PX)}</div>
            <ul className="acx-guided-face__lightbox-gallery" aria-label={person.name}>
              {person.galleryPhotos.map((photo) => (
                <li key={`enlarged-${photo.src}`}>
                  <img src={photo.src} alt={photo.altText} />
                  <span className="screen-reader-text">{photo.credit}</span>
                </li>
              ))}
            </ul>
            <p className="acx-guided-face__gallery-caption">{coverageCopy(coverage)}</p>
            <div className="acx-dialog__actions">
              <button
                type="button"
                className="acx-button acx-button--secondary"
                onClick={() => setComparisonOpen(false)}
              >
                {guidedCopy('names.evidence_close')}
              </button>
            </div>
          </DialogContent>
        </DialogPortal>
      </DialogRoot>
    </article>
  );
};

GuidedFaceMatchCard.displayName = 'GuidedFaceMatchCard';
