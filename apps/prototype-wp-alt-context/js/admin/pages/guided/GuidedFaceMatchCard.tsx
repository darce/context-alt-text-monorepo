import React, { useEffect, useRef, useState } from 'react';
import { AlertTriangle } from 'lucide-react';

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
  GUIDED_MATCH_STRENGTH,
  GUIDED_NAME_CHOICE,
  formatGuidedSimilarity,
  isClusterAnchor,
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
  onChoose: (choice: GuidedNameChoice, origin: HTMLInputElement, imageKey: GuidedImageKey) => void;
}

const INLINE_CROP_PX = 80;
const ENLARGED_CROP_PX = 160;

const IMAGE_COPY_KEYS: Record<GuidedImageKey, 'names.photo.tribeca' | 'names.photo.coachella'> = {
  tribeca: 'names.photo.tribeca',
  coachella: 'names.photo.coachella',
};

const coverageCopy = (coverage: GuidedNameCoverage): string =>
  coverage.shown === coverage.total
    ? guidedCopy('names.coverage_all', { total: coverage.total })
    : guidedCopy('names.coverage_partial', { shown: coverage.shown, total: coverage.total });

const imageLabel = (imageKey: GuidedImageKey): string => guidedCopy(IMAGE_COPY_KEYS[imageKey]);

const cropAlt = (match: GuidedFaceMatch): string =>
  guidedCopy('names.crop_alt_image', { position: match.face.position, image: imageLabel(match.face.imageKey) });

const isWeakMatch = (match: GuidedFaceMatch): boolean => match.face.strength === GUIDED_MATCH_STRENGTH.WEAK;

// The anchor face seeded the saved group, so it has no score worth showing.
const matchEvidenceCopy = (match: GuidedFaceMatch): string | null => {
  if (isClusterAnchor(match.face) || match.face.strength === GUIDED_MATCH_STRENGTH.SELF_ANCHOR) {
    return null;
  }
  if (match.face.similarity === null) {
    return guidedCopy('names.match.unavailable');
  }
  if (match.face.strength === GUIDED_MATCH_STRENGTH.WEAK) {
    return guidedCopy('names.weak.public', { similarity: formatGuidedSimilarity(match.face.similarity) });
  }
  if (match.face.strength === GUIDED_MATCH_STRENGTH.STRONG) {
    return guidedCopy('names.strong.public', { similarity: formatGuidedSimilarity(match.face.similarity) });
  }
  return guidedCopy('names.match.unavailable');
};

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
  const [lightboxCropSizePx, setLightboxCropSizePx] = useState(ENLARGED_CROP_PX);
  const [lightboxReferenceTile, setLightboxReferenceTile] = useState<HTMLImageElement | null>(null);
  const enlargeRef = useRef<HTMLButtonElement>(null);
  const wasComparisonOpenRef = useRef(false);
  const representative = matches[0]?.face;
  if (representative === undefined) {
    throw new Error(`Missing guided face matches for ${person.key}.`);
  }
  if (matches.some((match) => match.face.imageKey !== representative.imageKey)) {
    throw new Error(`Guided face match cards must contain matches from one photo (${representative.imageKey}).`);
  }
  const currentPhotoMatch = matches[0];
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

  useEffect(() => {
    if (!comparisonOpen || lightboxReferenceTile === null) {
      setLightboxCropSizePx(ENLARGED_CROP_PX);
      return;
    }

    const updateCropSize = (width: number): void => {
      if (Number.isFinite(width) && width > 0) {
        setLightboxCropSizePx(Math.round(width));
      }
    };
    updateCropSize(lightboxReferenceTile.getBoundingClientRect().width);

    if (typeof ResizeObserver === 'undefined') {
      return;
    }
    const resizeObserver = new ResizeObserver((entries) => {
      const tileEntry = entries.find((entry) => entry.target === lightboxReferenceTile);
      if (tileEntry !== undefined) {
        updateCropSize(tileEntry.contentRect.width);
      }
    });
    resizeObserver.observe(lightboxReferenceTile);
    return () => resizeObserver.disconnect();
  }, [comparisonOpen, lightboxReferenceTile]);

  const handleChange = (event: React.ChangeEvent<HTMLInputElement>, nextChoice: GuidedNameChoice): void => {
    onChoose(nextChoice, event.currentTarget, representative.imageKey);
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

  const matchEvidence = (match: GuidedFaceMatch): React.JSX.Element | null => {
    const copy = matchEvidenceCopy(match);
    if (copy === null) {
      return null;
    }
    return (
      <p
        className={
          isWeakMatch(match) ? 'acx-guided-face__match-line acx-guided-face__weak-match' : 'acx-guided-face__match-line'
        }
      >
        {isWeakMatch(match) ? (
          <span className="acx-guided-face__warning-icon" role="img" aria-label={guidedCopy('names.match.weak_icon')}>
            <AlertTriangle aria-hidden="true" size={16} />
          </span>
        ) : null}
        <span>{copy}</span>
      </p>
    );
  };

  return (
    <section aria-labelledby={titleId} className="acx-guided-face__card" data-image-key={representative.imageKey}>
      <div className="acx-guided-face__matches" data-testid={`face-matches-${person.key}`}>
        <ul className="acx-guided-face__match-list">
          {matches.map((match) => (
            <li key={match.face.id} className="acx-guided-face__match" style={{ minHeight: 64 }}>
              {thumbnail(match)}
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
          style={{ minHeight: 44 }}
        >
          {guidedCopy('names.compare.public')}
        </button>
      </div>
      <div className="acx-guided-face__content">
        <h5 id={titleId}>{person.name}</h5>

        <fieldset
          data-testid={`name-choice-${idScope}-${representative.position}`}
          disabled={disabled}
          className="acx-guided-face__choice"
        >
          <legend>{guidedCopy('names.legend', { position: representative.position })}</legend>
          <div className="acx-guided-face__choice-options">
            <label
              htmlFor={includeId}
              className="acx-guided-face__choice-option"
              style={{ display: 'flex', alignItems: 'center', gap: 8, minHeight: 44 }}
            >
              <input
                id={includeId}
                type="radio"
                name={groupName}
                value={GUIDED_NAME_CHOICE.USE}
                checked={choice === GUIDED_NAME_CHOICE.USE}
                onChange={(event) => handleChange(event, GUIDED_NAME_CHOICE.USE)}
              />
              {guidedCopy('names.use.public', { name: person.name })}
            </label>
            <label
              htmlFor={omitId}
              className="acx-guided-face__choice-option"
              style={{ display: 'flex', alignItems: 'center', gap: 8, minHeight: 44 }}
            >
              <input
                id={omitId}
                type="radio"
                name={groupName}
                value={GUIDED_NAME_CHOICE.LEAVE_UNNAMED}
                checked={choice === GUIDED_NAME_CHOICE.LEAVE_UNNAMED}
                onChange={(event) => handleChange(event, GUIDED_NAME_CHOICE.LEAVE_UNNAMED)}
              />
              {guidedCopy('names.omit.public')}
            </label>
          </div>
        </fieldset>
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
            <DialogTitle>{guidedCopy('lightbox.title.public', { name: person.name })}</DialogTitle>
            <DialogDescription>
              {guidedCopy('names.evidence_open', { position: representative.position })}
            </DialogDescription>
            <section className="acx-guided-face__lightbox-crop" aria-labelledby={`${groupName}-lightbox-current`}>
              <h3 id={`${groupName}-lightbox-current`}>{guidedCopy('lightbox.current.public')}</h3>
              {thumbnail(currentPhotoMatch, lightboxCropSizePx)}
              {matchEvidence(currentPhotoMatch)}
            </section>
            <section aria-labelledby={`${groupName}-lightbox-references`}>
              <h3 id={`${groupName}-lightbox-references`}>
                {guidedCopy('lightbox.references.public', { name: person.name })}
              </h3>
              <ul
                className="acx-guided-face__lightbox-gallery"
                aria-label={guidedCopy('lightbox.references.public', { name: person.name })}
              >
                {person.galleryPhotos.map((photo, index) => (
                  <li
                    key={`gallery-${photo.src}`}
                    className="acx-guided-face__lightbox-reference"
                    data-testid="guided-lightbox-reference-photo"
                  >
                    <img ref={index === 0 ? setLightboxReferenceTile : undefined} src={photo.src} alt={photo.altText} />
                    <p className="acx-guided-face__gallery-credit">{photo.credit}</p>
                  </li>
                ))}
              </ul>
              <p className="acx-guided-face__gallery-caption">{coverageCopy(coverage)}</p>
            </section>
            <div className="acx-dialog__actions">
              <button
                type="button"
                className="acx-button acx-button--secondary"
                onClick={() => setComparisonOpen(false)}
                style={{ minHeight: 44, minWidth: 44 }}
              >
                {guidedCopy('lightbox.close.public')}
              </button>
            </div>
          </DialogContent>
        </DialogPortal>
      </DialogRoot>
    </section>
  );
};

GuidedFaceMatchCard.displayName = 'GuidedFaceMatchCard';
