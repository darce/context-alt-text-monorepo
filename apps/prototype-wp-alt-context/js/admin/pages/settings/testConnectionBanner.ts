import { __, sprintf } from '@wordpress/i18n';

import {
  isTestConnectionOutcome,
  TestConnectionOutcome,
  type TestConnectionOutcomeValue,
  type TestConnectionResponse,
} from '../../api/settingsApi';

export type BannerTone = 'success' | 'warning' | 'error';

export interface BannerCopy {
  tone: BannerTone;
  role: 'status' | 'alert';
  primary: string;
  remediation: string;
}

export const TONE_CLASS: Record<BannerTone, string> = {
  success: 'notice-success',
  warning: 'notice-warning',
  error: 'notice-error',
};

const unknownOutcomeBanner = (): BannerCopy => ({
  tone: 'error',
  role: 'alert',
  primary: __('Unexpected response from the recognition service.', 'alt-context'),
  remediation: __(
    'The probe returned a response the plugin does not recognize. Confirm the recognition service and plugin are on compatible versions.',
    'alt-context',
  ),
});

export const renderBanner = (result: TestConnectionResponse): BannerCopy => {
  if (!isTestConnectionOutcome(result.outcome)) {
    return unknownOutcomeBanner();
  }
  const outcome: TestConnectionOutcomeValue = result.outcome;
  const isLocalProbe = result.probe_mode === 'local_liveness';
  switch (outcome) {
    case TestConnectionOutcome.CONNECTED:
      return {
        tone: 'success',
        role: 'status',
        primary: isLocalProbe
          ? __('Local recognition service is reachable.', 'alt-context')
          : __('Connection successful.', 'alt-context'),
        remediation: isLocalProbe
          ? __(
              'Scans route to this endpoint while recognition source is Local. Start the scan worker locally for processing.',
              'alt-context',
            )
          : __('The plugin authenticated against the recognition service and the pool is healthy.', 'alt-context'),
      };
    case TestConnectionOutcome.NOT_CONFIGURED:
      return {
        tone: 'warning',
        role: 'status',
        primary: __('No recognition URL configured.', 'alt-context'),
        remediation: __('Set the API URL above before testing.', 'alt-context'),
      };
    case TestConnectionOutcome.INVALID_KEY:
      return {
        tone: 'error',
        role: 'alert',
        primary: __('API key rejected.', 'alt-context'),
        remediation: __(
          'The recognition service returned 401/403. Check the API Key field above, or ask an operator to re-issue the key.',
          'alt-context',
        ),
      };
    case TestConnectionOutcome.EXPIRED:
      return {
        tone: 'error',
        role: 'alert',
        primary: __('API key expired.', 'alt-context'),
        remediation: __(
          'Ask an operator to rotate the key with the recognition CLI, then paste the new value here.',
          'alt-context',
        ),
      };
    case TestConnectionOutcome.REVOKED:
      return {
        tone: 'error',
        role: 'alert',
        primary: __('API key revoked.', 'alt-context'),
        remediation: __(
          'This key has been revoked server-side. Request a fresh key and update the value above.',
          'alt-context',
        ),
      };
    case TestConnectionOutcome.TENANT_MISMATCH:
      return {
        tone: 'error',
        role: 'alert',
        primary: __('Tenant mismatch.', 'alt-context'),
        remediation: __(
          'The API key belongs to a different site. Confirm the key was issued for this WordPress tenant.',
          'alt-context',
        ),
      };
    case TestConnectionOutcome.TENANT_PAIRING_CONFLICT:
      return {
        tone: 'warning',
        role: 'alert',
        primary: __('Tenant identity conflict.', 'alt-context'),
        remediation: __(
          'The API key is bound to a different tenant than this site. Confirm adoption before re-keying local data.',
          'alt-context',
        ),
      };
    case TestConnectionOutcome.RATE_LIMITED: {
      const seconds = result.retry_after_seconds;
      const wait =
        typeof seconds === 'number' && seconds > 0
          ? sprintf(
              /* translators: %d is the number of seconds to wait before retrying. */
              __('Retry after %d seconds.', 'alt-context'),
              seconds,
            )
          : __('Retry after a few seconds.', 'alt-context');
      return {
        tone: 'warning',
        role: 'status',
        primary: __('Recognition service is rate limiting this site.', 'alt-context'),
        remediation: wait,
      };
    }
    case TestConnectionOutcome.SERVER_ERROR:
      return {
        tone: 'error',
        role: 'alert',
        primary: __('Recognition service returned a server error.', 'alt-context'),
        remediation: __(
          'Try again in a moment. If the problem persists, check the recognition service logs.',
          'alt-context',
        ),
      };
    case TestConnectionOutcome.NETWORK_ERROR:
      return {
        tone: 'error',
        role: 'alert',
        primary: isLocalProbe
          ? __('Could not reach the local recognition service.', 'alt-context')
          : __('Could not reach the recognition service.', 'alt-context'),
        remediation: isLocalProbe
          ? __(
              'Start the local description service (make serve), confirm the Local service URL matches its port, then test again.',
              'alt-context',
            )
          : __('Verify the API URL above and confirm the site can reach the recognition host.', 'alt-context'),
      };
    case TestConnectionOutcome.TLS_ERROR:
      return {
        tone: 'error',
        role: 'alert',
        primary: __('TLS handshake failed.', 'alt-context'),
        remediation: __(
          'The recognition service certificate could not be validated. Check the HTTPS endpoint and trust chain.',
          'alt-context',
        ),
      };
    default: {
      const exhaustive: never = outcome;
      return exhaustive;
    }
  }
};
