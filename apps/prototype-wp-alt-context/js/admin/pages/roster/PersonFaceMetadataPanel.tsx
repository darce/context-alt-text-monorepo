import React from 'react';
import { __ } from '@wordpress/i18n';

import type { PersonScrubFace } from './personFaces';
import { getSelectedFaceMetadataLines } from './similarityCopy';

interface PersonFaceMetadataPanelProps {
  face: PersonScrubFace | null;
}

export const PersonFaceMetadataPanel = ({ face }: PersonFaceMetadataPanelProps): React.JSX.Element => {
  const lines = face
    ? getSelectedFaceMetadataLines({
        similarity: face.similarity,
        similarity_threshold: face.similarityThreshold,
      })
    : [];

  return (
    <section className="acx-roster__person-workspace-metadata" aria-label={__('Selected face details', 'alt-context')}>
      {face ? (
        <>
          {lines.map((line) => (
            <p key={line}>{line}</p>
          ))}
        </>
      ) : (
        <p>{__('No face selected.', 'alt-context')}</p>
      )}
    </section>
  );
};
