import React, { useMemo, useState } from 'react';

import { guidedCopy } from '../../guidedPrototype/publicGuideCopy';
import {
  createGuidedScenario,
  formatGuidedSimilarity,
  getGuidedPerson,
  GUIDED_MATCH_STRENGTH,
  GUIDED_MATCH_THRESHOLD,
  isClusterAnchor,
  type GuidedMatchStrength,
  type GuidedPressPhoto,
} from '../../guidedPrototype/state';
import { isUsableNaturalSize } from '../../../components/ui/faceGeometry';
import { GuidedFaceOverlay, type GuidedFaceOverlayFace } from './GuidedFaceOverlay';

export type GuidedSamplePhotoScope = 'public' | 'admin';

export interface GuidedSamplePhotoProps {
  photo: GuidedPressPhoto;
  /** Accepted for existing callers; the image alt always comes from currentAltText. */
  evidenceAlt?: string;
  currentAltText: string;
  /** Shows the current description below the photo in the admin guide. */
  showCurrentAltText: boolean;
  /** Accepted for existing callers that share this component between the admin and public guide. */
  scope: GuidedSamplePhotoScope;
  headingId?: string;
  children?: React.ReactNode;
}

const externalLinkLabel = (label: string): string => guidedCopy('context.external_link', { label });

const isExternalUrl = (value: string): boolean => /^https?:\/\//.test(value);

const publicOverlaySimilarityText = (
  similarity: number | null,
  strength: GuidedMatchStrength,
  anchor: boolean,
): string => {
  if (anchor) {
    return guidedCopy('names.no_score.public');
  }
  if (similarity === null) {
    return guidedCopy('names.match.unavailable');
  }
  return strength === GUIDED_MATCH_STRENGTH.WEAK ? guidedCopy('names.weak.public') : guidedCopy('names.strong.public');
};

const Credit = ({ photo }: { photo: GuidedPressPhoto }): React.JSX.Element => (
  <span>
    {isExternalUrl(photo.credit) ? (
      <a href={photo.credit} target="_blank" rel="noreferrer" aria-label={externalLinkLabel(photo.credit)}>
        {photo.credit}
      </a>
    ) : (
      photo.credit
    )}
  </span>
);

const AltTextAiCaption = ({ photo }: { photo: GuidedPressPhoto }): React.JSX.Element => {
  const caption = photo.altTextAiCaption;

  return (
    <details className="acx-guided-page__caption">
      <summary>{guidedCopy('comparison.alttextai.public')}</summary>
      <p>{guidedCopy('comparison.note.public')}</p>
      {caption.text === null ? <p>{guidedCopy('context.photo.no_caption')}</p> : <p>{caption.text}</p>}
      <p className="acx-guided-page__caption-provenance">
        <a href={caption.providerUrl} target="_blank" rel="noreferrer" aria-label={externalLinkLabel(caption.provider)}>
          {caption.provider}
        </a>
        {caption.capturedOn === null
          ? null
          : ` · ${guidedCopy('context.photo.captured', { date: caption.capturedOn })}`}
      </p>
    </details>
  );
};

const AdminPhotoCaptions = ({
  photo,
  currentAltText,
  showCurrentAltText,
}: {
  photo: GuidedPressPhoto;
  currentAltText: string;
  showCurrentAltText: boolean;
}): React.JSX.Element => {
  const generatedSentence = guidedCopy('context.photo.generated', {
    date: photo.altContextDescription.generatedOn,
    system: '__system__',
  });
  const [generatedBeforeSystem, generatedAfterSystem = ''] = generatedSentence.split('__system__');

  return (
    <figcaption>
      {showCurrentAltText ? (
        <p>
          {guidedCopy('context.current_label')}: {currentAltText}
        </p>
      ) : null}
      <div className="acx-guided-page__caption-compare">
        <section className="acx-guided-page__caption">
          <h4>{guidedCopy('context.photo.altcontext_title')}</h4>
          <p>{photo.altContextDescription.text}</p>
          <p className="acx-guided-page__caption-provenance">
            {generatedBeforeSystem}
            <a
              href={photo.altContextDescription.systemUrl}
              target="_blank"
              rel="noreferrer"
              aria-label={externalLinkLabel(photo.altContextDescription.system)}
            >
              {photo.altContextDescription.system}
            </a>
            {generatedAfterSystem}
          </p>
        </section>
        <section className="acx-guided-page__caption">
          <h4>{guidedCopy('context.photo.alttextai_title')}</h4>
          {photo.altTextAiCaption.text === null ? (
            <p>{guidedCopy('context.photo.no_caption')}</p>
          ) : (
            <p>{photo.altTextAiCaption.text}</p>
          )}
          <p className="acx-guided-page__caption-provenance">
            <a
              href={photo.altTextAiCaption.providerUrl}
              target="_blank"
              rel="noreferrer"
              aria-label={externalLinkLabel(photo.altTextAiCaption.provider)}
            >
              {photo.altTextAiCaption.provider}
            </a>
            {photo.altTextAiCaption.capturedOn === null
              ? null
              : ` · ${guidedCopy('context.photo.captured', { date: photo.altTextAiCaption.capturedOn })}`}
          </p>
        </section>
      </div>
    </figcaption>
  );
};

const overlayFacesForPhoto = (photo: GuidedPressPhoto, scope: GuidedSamplePhotoScope): GuidedFaceOverlayFace[] => {
  const scenario = createGuidedScenario();

  return scenario.faces
    .filter((face) => face.imageKey === photo.key)
    .map((face) => {
      const person = getGuidedPerson(scenario, face.matchedPersonKey);
      const anchor = isClusterAnchor(face);
      const strength =
        (face.similarity !== null && face.similarity < GUIDED_MATCH_THRESHOLD) ||
        face.strength === GUIDED_MATCH_STRENGTH.WEAK
          ? GUIDED_MATCH_STRENGTH.WEAK
          : GUIDED_MATCH_STRENGTH.STRONG;
      const publicStrength = face.strength ?? strength;
      const similarityText =
        scope === 'admin'
          ? face.similarity === null
            ? guidedCopy('names.match.unavailable')
            : formatGuidedSimilarity(face.similarity)
          : publicOverlaySimilarityText(face.similarity, publicStrength, anchor);

      return {
        id: face.id,
        box: face.box,
        label: person.name,
        similarityText,
        strength: scope === 'public' ? publicStrength : strength,
        ...(scope === 'public' ? { isClusterAnchor: anchor } : {}),
      };
    });
};

export const GuidedSamplePhoto = ({
  photo,
  currentAltText,
  showCurrentAltText,
  scope,
  headingId,
  children,
}: GuidedSamplePhotoProps): React.JSX.Element => {
  const [imageFailed, setImageFailed] = useState(false);
  const [naturalSize, setNaturalSize] = useState({ width: 0, height: 0 });
  const [pointerInside, setPointerInside] = useState(false);
  const [focusWithin, setFocusWithin] = useState(false);
  const accessibleAlt = currentAltText;
  const overlayFaces = useMemo(() => overlayFacesForPhoto(photo, scope), [photo, scope]);
  const overlayVisible = pointerInside || focusWithin;
  const imageLoaded = isUsableNaturalSize(naturalSize);
  const imageOrientation = imageLoaded && naturalSize.width / naturalSize.height < 1 ? 'portrait' : 'landscape';

  const handleFigureBlur = (event: React.FocusEvent<HTMLElement>): void => {
    if (event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget)) {
      return;
    }
    setFocusWithin(false);
  };

  return (
    <figure
      className="acx-guided-page__media-card"
      data-testid={`guided-photo-${photo.key}`}
      aria-labelledby={headingId}
      onPointerEnter={() => setPointerInside(true)}
      onPointerLeave={() => setPointerInside(false)}
      onFocus={() => setFocusWithin(true)}
      onBlur={handleFigureBlur}
    >
      <h3 id={headingId}>{photo.event}</h3>
      {imageFailed ? (
        <div
          className="acx-guided-page__image-placeholder acx-guided-page__image-placeholder--fallback"
          role="img"
          aria-label={accessibleAlt}
        >
          <span>{accessibleAlt}</span>
        </div>
      ) : (
        <div
          className="acx-guided-page__image-wrap"
          data-orientation={imageOrientation}
          style={
            imageLoaded
              ? ({ '--acx-guided-photo-ratio': `${naturalSize.width} / ${naturalSize.height}` } as React.CSSProperties)
              : undefined
          }
        >
          <div className="acx-guided-page__image-frame">
            <img
              className="acx-guided-page__image"
              src={photo.src}
              alt={accessibleAlt}
              onLoad={(event) =>
                setNaturalSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })
              }
              onError={() => setImageFailed(true)}
            />
            <GuidedFaceOverlay
              faces={imageLoaded ? overlayFaces : []}
              naturalSize={naturalSize}
              visible={overlayVisible}
              idPrefix={`guided-${photo.key}`}
            />
          </div>
        </div>
      )}
      <p className="acx-guided-page__credit">
        {guidedCopy('context.photo.credit_label')}: <Credit photo={photo} />
      </p>
      {scope === 'public' ? (
        <figcaption>
          <AltTextAiCaption photo={photo} />
        </figcaption>
      ) : (
        <AdminPhotoCaptions photo={photo} currentAltText={currentAltText} showCurrentAltText={showCurrentAltText} />
      )}
      {children}
    </figure>
  );
};

GuidedSamplePhoto.displayName = 'GuidedSamplePhoto';
