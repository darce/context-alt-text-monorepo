import React from 'react';
import { __ } from '@wordpress/i18n';

import type { TestConnectionResponse } from '../../api/settingsApi';
import { renderBanner, TONE_CLASS } from './testConnectionBanner';

interface TestConnectionBannerViewProps {
  testResult: TestConnectionResponse;
}

export const TestConnectionBannerView = ({ testResult }: TestConnectionBannerViewProps): React.JSX.Element => {
  const banner = renderBanner(testResult);

  return (
    <div
      className={`notice inline ${TONE_CLASS[banner.tone]}`}
      role={banner.role}
      style={{ marginTop: '12px' }}
      data-testid="acx-test-connection-banner"
      data-outcome={testResult.outcome}
    >
      <p>{banner.primary}</p>
      <p>{banner.remediation}</p>
      {testResult.probed_url ? (
        <p>
          {__('Probed', 'alt-context')}: <code>{testResult.probed_url}</code>
        </p>
      ) : null}
    </div>
  );
};