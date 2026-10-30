import React from 'react';
import { __ } from '@wordpress/i18n';

import { GPU_STATE_VOCABULARY } from './gpuStatePresentation';

export const BetaExpectationsNotice = (): React.JSX.Element => (
  <div className="acx-notice acx-notice--info" data-testid="beta-expectations-notice">
    <p>{__('Beta: descriptions are AI-generated drafts to review before publishing.', 'alt-context')}</p>
    <details>
      <summary>{__('What to expect', 'alt-context')}</summary>
      <p>
        {__(
          "Expect to correct some drafts, especially unsupported details, who does what, counts and attributes, text in the image, and people's names.",
          'alt-context',
        )}
      </p>
      <p>{GPU_STATE_VOCABULARY.coldStartWait}</p>
      <p>{__('You decide which drafts to edit and publish.', 'alt-context')}</p>
    </details>
  </div>
);
