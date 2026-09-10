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
import { guidedCopy } from '../../guidedPrototype/publicGuideCopy';
import {
  formatGuidedSimilarity,
  GUIDED_MATCH_STRENGTH,
  GUIDED_MATCH_THRESHOLD,
  GUIDED_NAME_CHOICE,
  type GuidedFace,
  type GuidedImageKey,
  type GuidedLabeledPerson,
  type GuidedNameChoice,
  type GuidedNameCoverage,
} from '../../guidedPrototype/state';

export interface GuidedFaceMatch {
  face: GuidedFace;
  mediaUrl: string;
}

export interface GuidedFaceMatchCardProps {
  matches: GuidedFaceMatch[];
  person: GuidedLabeledPerson;
  coverage: GuidedNameCoverage;
  choice: GuidedNameChoice;
  idScope: string;
  disabled: boolean;
  onChoose: (choice: GuidedNameChoice, origin: HTMLInputElement) => void;
}

const INLINE_CROP_PX = 80;
const ENLARGED_CROP_PX = 240;

const IMAGE_COPY_KEYS: Record<GuidedImageKey, 'names.photo.tribeca' | 'names.photo.coachella'> = {
  tribeca: 'names.photo.tribeca',
  coachella: 'names.photo.coachella',
};

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

const imageLabel = (imageKey: GuidedImageKey): string => guidedCopy(IMAGE_COPY_KEYS[imageKey]);

const cropAlt = (match: GuidedFaceMatch): string =>
  guidedCopy('names.crop_alt_image', { position: match.face.position, image: imageLabel(match.face.imageKey) });

const strengthLabel = (match: GuidedFaceMatch): string => {
  const strength = guidedCopy(
    match.face.strength === GUIDED_MATCH_STRENGTH.WEAK ? 'names.match.weak' : 'names.match.strong',
  );
  if (match.face.isClusterAnchor) {
    return `${guidedCopy('names.match.cluster_anchor')}, ${strength}`;
  }
  return strength;
};

const matchSummary = (match: GuidedFaceMatch): string =>
  guidedCopy('names.match', {
    image: imageLabel(match.face.imageKey),
    similarity:
      match.face.similarity === null
        ? guidedCopy('names.match.unavailable')
        : formatGuidedSimilarity(match.face.similarity),
    strength: strengthLabel(match),
  });

const isWeakMatch = (match: GuidedFaceMatch): boolean =>
  match.face.strength === GUIDED_MATCH_STRENGTH.WEAK ||
  (match.face.similarity !== null && match.face.similarity < GUIDED_MATCH_THRESHOLD);

export const GuidedFaceMatchCard = ({
  matches,
  person,
  coverage,
  choice,
  idScope,
  disabled,
  onChoose,
}: GuidedFaceMatchCardProps): React.JSX.Element => {
  const [comparisonOpen, setComparisonOpen] = useState(false);
  const enlargeRef = useRef<HTMLButtonElement>(null);
  const wasComparisonOpenRef = useRef(false);
  const representative = matches[0]?.face;
  if (representative === undefined) {
    throw new Error(`Missing guided face matches for ${person.key}.`);
  }
  const titleId = `guided-face-${idScope}-${person.key}-title`;
  const groupName = `guided-name-${idScope}-${representative.position}`;
  const includeId = `${groupName}-include`;
  const omitId = `${groupName}-omit`;
  const enlargeId = `${groupName}-enlarge`;

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

  const thumbnail = (match: GuidedFaceMatch, sizePx = INLINE_CROP_PX): React.JSX.Element => (
    <FaceThumbnail
      mediaUrl={match.mediaUrl}
      bbox={match.face.box}
      size="lg"
      sizePx={sizePx}
      shape="square"
      alt={cropAlt(match)}
    />
  );

  const matchEvidence = (match: GuidedFaceMatch): React.JSX.Element => (
    <>
      <p className="acx-guided-face__match-summary">{matchSummary(match)}</p>
      {isWeakMatch(match) ? (
        <p className="acx-guided-face__weak-match">
          <span role="img" aria-label={guidedCopy('names.match.weak_icon')}>
            ⚠
          </span>{' '}
          {guidedCopy('names.match.below_threshold', {
            threshold: formatGuidedSimilarity(GUIDED_MATCH_THRESHOLD),
          })}
        </p>
      ) : null}
    </>
  );

  return (
    <section aria-labelledby={titleId} className="acx-guided-face__card">
      <div className="acx-guided-face__matches" data-testid={`face-matches-${person.key}`}>
        <ul className="acx-guided-face__match-list">
          {matches.map((match) => (
            <li key={match.face.id} className="acx-guided-face__match">
              {thumbnail(match)}
              <p className="acx-guided-face__match-image">{imageLabel(match.face.imageKey)}</p>
              {matchEvidence(match)}
            </li>
          ))}
        </ul>
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
        <h5 id={titleId}>{guidedCopy('names.suggestion', { name: person.name })}</h5>

        <details className="acx-guided-face__evidence" open>
          <summary>{guidedCopy('names.evidence_open', { position: representative.position })}</summary>
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

        <fieldset
          data-testid={`name-choice-${idScope}-${representative.position}`}
          disabled={disabled}
          className="acx-guided-face__choice"
        >
          <legend>{guidedCopy('names.legend', { position: representative.position })}</legend>
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
            <DialogDescription>
              {guidedCopy('names.evidence_open', { position: representative.position })}
            </DialogDescription>
            <ul className="acx-guided-face__lightbox-matches">
              {matches.map((match) => (
                <li key={`enlarged-${match.face.id}`}>
                  {thumbnail(match, ENLARGED_CROP_PX)}
                  <p className="acx-guided-face__match-image">{imageLabel(match.face.imageKey)}</p>
                  {matchEvidence(match)}
                </li>
              ))}
            </ul>
            <ul className="acx-guided-face__lightbox-gallery" aria-label={person.name}>
              {person.galleryPhotos.map((photo) => (
                <li key={`gallery-${photo.src}`}>
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
    </section>
  );
};

GuidedFaceMatchCard.displayName = 'GuidedFaceMatchCard';
