import React from 'react';

import { guidedCopy } from '../../guidedPrototype/publicGuideCopy';

export interface GuidedDesignNotesProps {
  scope?: 'public' | 'admin';
}

export const GuidedDesignNotes = ({ scope = 'admin' }: GuidedDesignNotesProps): React.JSX.Element => (
  <details className="acx-guided-notes">
    <summary>{guidedCopy('notes.title')}</summary>
    <ul>
      <li>{guidedCopy(scope === 'public' ? 'notes.recorded_public' : 'notes.recorded')}</li>
      <li>{guidedCopy('notes.names')}</li>
      <li>{guidedCopy('notes.apply')}</li>
      <li>{guidedCopy('notes.scope')}</li>
    </ul>
  </details>
);

GuidedDesignNotes.displayName = 'GuidedDesignNotes';
