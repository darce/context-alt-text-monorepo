import React, { useMemo, useState } from 'react';

import { guidedCopy } from '../../guidedPrototype/publicGuideCopy';
import {
  createGuidedScenario,
  formatGuidedSimilarity,
  getGuidedPerson,
  GUIDED_MATCH_THRESHOLD,
  type GuidedPressPhoto,
  type GuidedProvenance,
} from '../../guidedPrototype/state';
import { isUsableNaturalSize } from '../../../components/ui/faceGeometry';
import { GuidedFaceOverlay, type GuidedFaceOverlayFace } from './GuidedFaceOverlay';

export type GuidedSamplePhotoScope = 'public' | 'admin';

export interface GuidedSamplePhotoProps {
  photo: GuidedPressPhoto;
  evidenceAlt?: string;
  currentAltText: string;
  showCurrentAltText: boolean;
  provenance: GuidedProvenance;
  scope: GuidedSamplePhotoScope;
  publicSourceSummary?: React.ReactNode;
  headingId?: string;
  children?: React.ReactNode;
}

const externalLinkLabel = (label: string): string => guidedCopy('context.external_link', { label });

const isExternalUrl = (value: string): boolean => /^https?:\/\//.test(value);

const Credit = ({ photo }: { photo: GuidedPressPhoto }): React.JSX.Element => (
  <span>
    <strong>{guidedCopy('context.photo.credit_label')}:</strong>{' '}
    {isExternalUrl(photo.credit) ? (
      <a href={photo.credit} target="_blank" rel="noreferrer" aria-label={externalLinkLabel(photo.credit)}>
        {photo.credit}
      </a>
    ) : (
      photo.credit
    )}
  </span>
);

const GeneratedAttribution = ({ photo }: { photo: GuidedPressPhoto }): React.JSX.Element => {
  const caption = photo.altContextDescription;
  const generatedText = guidedCopy('context.photo.generated', {
    date: caption.generatedOn,
    system: caption.system,
  });
  const systemStart = generatedText.indexOf(caption.system);

  if (systemStart < 0) {
    return <>{generatedText}</>;
  }

  return (
    <>
      {generatedText.slice(0, systemStart)}
      <a href={caption.systemUrl} target="_blank" rel="noreferrer" aria-label={externalLinkLabel(caption.system)}>
        {caption.system}
      </a>
      {generatedText.slice(systemStart + caption.system.length)}
    </>
  );
};

const AltTextAiCaption = ({ photo }: { photo: GuidedPressPhoto }): React.JSX.Element => {
  const caption = photo.altTextAiCaption;

  return (
    <details className="acx-guided-page__caption">
      <summary>{guidedCopy('context.photo.alttextai_title')}</summary>
      <section aria-labelledby={`guided-caption-${photo.key}-alttextai`}>
        <h4 id={`guided-caption-${photo.key}-alttextai`}>{guidedCopy('context.photo.alttextai_title')}</h4>
        {caption.text === null ? <p>{guidedCopy('context.photo.no_caption')}</p> : <p>{caption.text}</p>}
        <p className="acx-guided-page__caption-provenance">
          <a
            href={caption.providerUrl}
            target="_blank"
            rel="noreferrer"
            aria-label={externalLinkLabel(caption.provider)}
          >
            {caption.provider}
          </a>{' '}
          {caption.capturedOn === null ? null : guidedCopy('context.photo.captured', { date: caption.capturedOn })}{' '}
          {caption.note}
        </p>
      </section>
    </details>
  );
};

const AltContextCaption = ({ photo }: { photo: GuidedPressPhoto }): React.JSX.Element => {
  const caption = photo.altContextDescription;

  return (
    <details className="acx-guided-page__caption">
      <summary>{guidedCopy('context.photo.altcontext_title')}</summary>
      <section aria-labelledby={`guided-caption-${photo.key}-altcontext`}>
        <h4 id={`guided-caption-${photo.key}-altcontext`}>{guidedCopy('context.photo.altcontext_title')}</h4>
        <p>{caption.text}</p>
        <p className="acx-guided-page__caption-provenance">
          <GeneratedAttribution photo={photo} />
        </p>
      </section>
    </details>
  );
};

const PhotoCredits = ({ photo }: { photo: GuidedPressPhoto }): React.JSX.Element => (
  <details className="acx-guided-page__caption">
    <summary>{guidedCopy('context.photo.credit_label')}</summary>
    <Credit photo={photo} />
    {photo.source !== undefined && photo.source !== photo.credit ? <p>{photo.source}</p> : null}
  </details>
);

const overlayFacesForPhoto = (photo: GuidedPressPhoto): GuidedFaceOverlayFace[] => {
  const scenario = createGuidedScenario();

  return scenario.faces
    .filter((face) => face.imageKey === photo.key)
    .map((face) => {
      const person = getGuidedPerson(scenario, face.matchedPersonKey);
      const similarityText =
        face.similarity === null ? guidedCopy('names.match.unavailable') : formatGuidedSimilarity(face.similarity);

      return {
        id: face.id,
        box: face.box,
        label: person.name,
        similarityText,
        strength:
          (face.similarity !== null && face.similarity < GUIDED_MATCH_THRESHOLD) || face.strength === 'weak'
            ? 'weak'
            : 'strong',
      };
    });
};

export const GuidedSamplePhoto = ({
  photo,
  evidenceAlt,
  currentAltText,
  showCurrentAltText,
  provenance,
  scope,
  publicSourceSummary,
  headingId,
  children,
}: GuidedSamplePhotoProps): React.JSX.Element => {
  const [imageFailed, setImageFailed] = useState(false);
  const [naturalSize, setNaturalSize] = useState({ width: 0, height: 0 });
  const [pointerInside, setPointerInside] = useState(false);
  const [focusWithin, setFocusWithin] = useState(false);
  const accessibleAlt = evidenceAlt ?? photo.altText;
  const overlayFaces = useMemo(() => overlayFacesForPhoto(photo), [photo]);
  const overlayVisible = pointerInside || focusWithin;
  const imageLoaded = isUsableNaturalSize(naturalSize);

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
      <h3>{photo.event}</h3>
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
          style={{
            position: 'relative',
            ...(imageLoaded
              ? { aspectRatio: `${naturalSize.width} / ${naturalSize.height}` }
              : { minHeight: '12rem' }),
          }}
        >
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
      )}
      <figcaption>
        {showCurrentAltText ? (
          <span>
            {guidedCopy('context.current_label')}: {currentAltText}
          </span>
        ) : null}
        <AltTextAiCaption photo={photo} />
        <AltContextCaption photo={photo} />
        <PhotoCredits photo={photo} />
        <details className="acx-guided-page__provenance">
          <summary>{guidedCopy('provenance.disclosure')}</summary>
          {scope === 'public' && publicSourceSummary !== undefined ? <p>{publicSourceSummary}</p> : null}
          {scope === 'public' ? <p>{guidedCopy('context.source.comparison_boundary.public')}</p> : null}
          <p>{guidedCopy('provenance.recorded')}</p>
          <p>{photo.event}</p>
          <p>{provenance.alsoChecked}</p>
        </details>
        {children}
      </figcaption>
    </figure>
  );
};

GuidedSamplePhoto.displayName = 'GuidedSamplePhoto';
