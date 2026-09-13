import React, { useMemo, useState } from 'react';

import { guidedCopy } from '../../guidedPrototype/publicGuideCopy';
import {
  createGuidedScenario,
  formatGuidedSimilarity,
  getGuidedPerson,
  GUIDED_MATCH_THRESHOLD,
  type GuidedPressPhoto,
} from '../../guidedPrototype/state';
import { isUsableNaturalSize } from '../../../components/ui/faceGeometry';
import { GuidedFaceOverlay, type GuidedFaceOverlayFace } from './GuidedFaceOverlay';

export type GuidedSamplePhotoScope = 'public' | 'admin';

const GUIDED_SAMPLE_PHOTO_SCOPE = {
  PUBLIC: 'public',
  ADMIN: 'admin',
} as const;

export interface GuidedSamplePhotoProps {
  photo: GuidedPressPhoto;
  evidenceAlt?: string;
  currentAltText: string;
  showCurrentAltText: boolean;
  scope: GuidedSamplePhotoScope;
  headingId?: string;
  children?: React.ReactNode;
}

const externalLinkLabel = (label: string): string => guidedCopy('context.external_link', { label });

const isExternalUrl = (value: string): boolean => /^https?:\/\//.test(value);

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

const AltTextAiCaption = ({
  photo,
  scope,
}: {
  photo: GuidedPressPhoto;
  scope: GuidedSamplePhotoScope;
}): React.JSX.Element => {
  const caption = photo.altTextAiCaption;
  const title =
    scope === GUIDED_SAMPLE_PHOTO_SCOPE.PUBLIC
      ? guidedCopy('comparison.alttextai.public')
      : guidedCopy('context.photo.alttextai_title');

  return (
    <section className="acx-guided-page__caption" aria-labelledby={`guided-caption-${photo.key}-alttextai`}>
      <h4 id={`guided-caption-${photo.key}-alttextai`}>{title}</h4>
      {caption.text === null ? <p>{guidedCopy('context.photo.no_caption')}</p> : <p>{caption.text}</p>}
      <p className="acx-guided-page__caption-provenance">
        <a href={caption.providerUrl} target="_blank" rel="noreferrer" aria-label={externalLinkLabel(caption.provider)}>
          {caption.provider}
        </a>
        {caption.capturedOn === null
          ? null
          : ` · ${guidedCopy('context.photo.captured', { date: caption.capturedOn })}`}
      </p>
    </section>
  );
};

const AltContextCaption = ({
  photo,
  scope,
}: {
  photo: GuidedPressPhoto;
  scope: GuidedSamplePhotoScope;
}): React.JSX.Element => {
  const caption = photo.altContextDescription;
  const title =
    scope === GUIDED_SAMPLE_PHOTO_SCOPE.PUBLIC
      ? guidedCopy('comparison.altcontext.public')
      : guidedCopy('context.photo.altcontext_title');

  return (
    <section className="acx-guided-page__caption" aria-labelledby={`guided-caption-${photo.key}-altcontext`}>
      <h4 id={`guided-caption-${photo.key}-altcontext`}>{title}</h4>
      <p>{caption.text}</p>
      <p className="acx-guided-page__caption-provenance">
        <GeneratedAttribution photo={photo} />
      </p>
    </section>
  );
};

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
  scope,
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
      <figcaption>
        {scope === GUIDED_SAMPLE_PHOTO_SCOPE.ADMIN && showCurrentAltText ? (
          <span>
            {guidedCopy('context.current_label')}: {currentAltText}
          </span>
        ) : null}
        <div className="acx-guided-page__caption-compare">
          <AltContextCaption photo={photo} scope={scope} />
          <AltTextAiCaption photo={photo} scope={scope} />
        </div>
      </figcaption>
      {children}
    </figure>
  );
};

GuidedSamplePhoto.displayName = 'GuidedSamplePhoto';
