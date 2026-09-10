import React, { useState } from 'react';

import { guidedCopy } from '../../guidedPrototype/publicGuideCopy';
import type { GuidedPressPhoto, GuidedProvenance } from '../../guidedPrototype/state';

export type GuidedSamplePhotoScope = 'public' | 'admin';

export interface GuidedSamplePhotoProps {
  photo: GuidedPressPhoto;
  evidenceAlt?: string;
  currentAltText: string;
  showCurrentAltText: boolean;
  provenance: GuidedProvenance;
  scope: GuidedSamplePhotoScope;
  publicSourceSummary?: React.ReactNode;
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

const AltTextAiCaption = ({ photo }: { photo: GuidedPressPhoto }): React.JSX.Element => {
  const caption = photo.altTextAiCaption;

  return (
    <section className="acx-guided-page__caption" aria-labelledby={`guided-caption-${photo.key}-alttextai`}>
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
        {caption.capturedOn === null
          ? null
          : guidedCopy('context.photo.captured', { date: caption.capturedOn })}{' '}
        {caption.note}
      </p>
    </section>
  );
};

const AltContextCaption = ({ photo }: { photo: GuidedPressPhoto }): React.JSX.Element => {
  const caption = photo.altContextDescription;

  return (
    <section className="acx-guided-page__caption" aria-labelledby={`guided-caption-${photo.key}-altcontext`}>
      <h4 id={`guided-caption-${photo.key}-altcontext`}>{guidedCopy('context.photo.altcontext_title')}</h4>
      <p>
        <strong>{guidedCopy('context.photo.altcontext_no_context')}:</strong> {caption.noContext}
      </p>
      <p>
        <strong>{guidedCopy('context.photo.altcontext_with_names')}:</strong> {caption.withNames}
      </p>
      <p className="acx-guided-page__caption-provenance">
        <a
          href={caption.systemUrl}
          target="_blank"
          rel="noreferrer"
          aria-label={externalLinkLabel(caption.system)}
        >
          {caption.system}
        </a>{' '}
        {guidedCopy('context.photo.generated', { date: caption.generatedOn, system: caption.system })}{' '}
        {guidedCopy('context.photo.model', { model: caption.model, quantization: caption.quantization })}{' '}
        {guidedCopy('context.photo.revision', { revision: caption.modelRevision })}{' '}
        {caption.note}
      </p>
    </section>
  );
};

export const GuidedSamplePhoto = ({
  photo,
  evidenceAlt,
  currentAltText,
  showCurrentAltText,
  provenance,
  scope,
  publicSourceSummary,
}: GuidedSamplePhotoProps): React.JSX.Element => {
  const [imageFailed, setImageFailed] = useState(false);
  const accessibleAlt = evidenceAlt ?? photo.altText;

  return (
    <figure className="acx-guided-page__media-card" data-testid={`guided-photo-${photo.key}`}>
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
        <img className="acx-guided-page__image" src={photo.src} alt={accessibleAlt} onError={() => setImageFailed(true)} />
      )}
      <figcaption>
        {showCurrentAltText ? (
          <span>
            {guidedCopy('context.current_label')}: {currentAltText}
          </span>
        ) : null}
        <Credit photo={photo} />
        <AltTextAiCaption photo={photo} />
        <AltContextCaption photo={photo} />
        <details className="acx-guided-page__provenance">
          <summary>{guidedCopy('provenance.disclosure')}</summary>
          {scope === 'public' && publicSourceSummary !== undefined ? <p>{publicSourceSummary}</p> : null}
          {scope === 'public' ? <p>{guidedCopy('context.source.comparison_boundary.public')}</p> : null}
          <p>{guidedCopy('provenance.recorded')}</p>
          <p>{photo.event}</p>
          <Credit photo={photo} />
          {photo.source !== undefined && photo.source !== photo.credit ? <p>{photo.source}</p> : null}
          <p>{provenance.alsoChecked}</p>
        </details>
      </figcaption>
    </figure>
  );
};

GuidedSamplePhoto.displayName = 'GuidedSamplePhoto';
