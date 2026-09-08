import React from 'react';

import { guidedCopy } from '../../guidedPrototype/copy';

export const GuidedDesignNotes = (): React.JSX.Element => (
  <details className="acx-guided-notes">
    <summary>{guidedCopy('notes.title')}</summary>
    <ul>
      <li>{guidedCopy('notes.recorded')}</li>
      <li>{guidedCopy('notes.names')}</li>
      <li>{guidedCopy('notes.apply')}</li>
      <li>{guidedCopy('notes.scope')}</li>
    </ul>
  </details>
);

GuidedDesignNotes.displayName = 'GuidedDesignNotes';
