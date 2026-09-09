import React from 'react';

import { guidedCopy as catalogCopy } from '../../guidedPrototype/copy';
import { guidedCopy } from '../../guidedPrototype/publicGuideCopy';

export interface GuidedDesignNotesProps {
  scope?: 'public' | 'admin';
}

export const GuidedDesignNotes = ({ scope = 'admin' }: GuidedDesignNotesProps): React.JSX.Element => (
  <details className="acx-guided-notes">
    <summary>{catalogCopy('notes.title')}</summary>
    <ul>
      <li>{scope === 'public' ? guidedCopy('notes.recorded_public') : catalogCopy('notes.recorded')}</li>
      <li>{catalogCopy('notes.names')}</li>
      <li>{catalogCopy('notes.apply')}</li>
      <li>{catalogCopy('notes.scope')}</li>
    </ul>
  </details>
);

GuidedDesignNotes.displayName = 'GuidedDesignNotes';
