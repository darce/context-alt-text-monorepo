import React from 'react';
import { __ } from '@wordpress/i18n';

import { TestConnectionOutcome, type TestConnectionResponse } from '../../api/settingsApi';
import { renderBanner, TONE_CLASS } from './testConnectionBanner';

interface TestConnectionBannerViewProps {
  testResult: TestConnectionResponse;
  onConfirmTenantPairing?: () => void;
  confirmPending?: boolean;
}

export const TestConnectionBannerView = ({
  testResult,
  onConfirmTenantPairing,
  confirmPending = false,
}: TestConnectionBannerViewProps): React.JSX.Element => {
  const banner = renderBanner(testResult);
  const showPairingConfirm = testResult.outcome === TestConnectionOutcome.TENANT_PAIRING_CONFLICT;

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
      {showPairingConfirm && testResult.persisted_tenant_id && testResult.key_tenant_id ? (
        <p>
          {__('Persisted tenant', 'alt-context')}: <code>{testResult.persisted_tenant_id}</code>
          <br />
          {__('API key tenant', 'alt-context')}: <code>{testResult.key_tenant_id}</code>
        </p>
      ) : null}
      {showPairingConfirm && onConfirmTenantPairing ? (
        <p>
          <button
            type="button"
            className="button button-secondary"
            onClick={onConfirmTenantPairing}
            disabled={confirmPending}
            data-testid="acx-confirm-tenant-pairing"
          >
            {confirmPending
              ? __('Adopting tenant identity…', 'alt-context')
              : __('Adopt API key tenant', 'alt-context')}
          </button>
        </p>
      ) : null}
      {testResult.probed_url ? (
        <p>
          {__('Probed', 'alt-context')}: <code>{testResult.probed_url}</code>
        </p>
      ) : null}
    </div>
  );
};