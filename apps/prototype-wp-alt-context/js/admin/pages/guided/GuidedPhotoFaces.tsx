import React from 'react';

import type { GuidedImageKey } from '../../guidedPrototype/state';

export interface GuidedPhotoFacesProps {
  photoKey: GuidedImageKey;
  title: string;
  children: React.ReactNode;
}

export const GuidedPhotoFaces: React.FC<GuidedPhotoFacesProps> = ({ photoKey, title, children }) => {
  const titleId = `guided-faces-${photoKey}-title`;

  return (
    <article className="acx-guided-page__faces" aria-labelledby={titleId} data-testid={`guided-faces-${photoKey}`}>
      <h4 id={titleId}>{title}</h4>
      <div className="acx-guided-page__faces-list">{children}</div>
    </article>
  );
};

GuidedPhotoFaces.displayName = 'GuidedPhotoFaces';
