import { __, sprintf } from '@wordpress/i18n';

import {
  isTestConnectionOutcome,
  TestConnectionOutcome,
  type TestConnectionOutcomeValue,
  type TestConnectionResponse,
} from '../../api/settingsApi';

export type BannerTone = 'success' | 'warning' | 'error' | 'info';

export interface BannerCopy {
  tone: BannerTone;
  role: 'status' | 'alert';
  primary: string;
  remediation: string;
  /** Status glyph paired with tone colour ([sr-004]); do not rely on colour alone. */
  icon: string;
  // When true, the banner offers a "confirm/adopt tenant pairing" action. Both the paired-elsewhere
  // conflict and the first-time mismatch are recoverable by explicitly adopting the key's tenant.
  confirmPairing?: boolean;
}

export const TONE_CLASS: Record<BannerTone, string> = {
  success: 'notice-success',
  warning: 'notice-warning',
  error: 'notice-error',
  info: 'notice-info',
};

export const TONE_ICON: Record<BannerTone, string> = {
  success: '\u2713',
  warning: '\u26a0',
  error: '\u26a0',
  info: '\u2139',
};

const banner = (
  tone: BannerTone,
  role: BannerCopy['role'],
  primary: string,
  remediation: string,
  extra: Pick<BannerCopy, 'confirmPairing'> & { prefixIcon?: boolean } = {},
): BannerCopy => {
  const icon = TONE_ICON[tone];
  const { prefixIcon, ...rest } = extra;
  return {
    tone,
    role,
    icon,
    primary: prefixIcon === true ? `${icon} ${primary}` : primary,
    remediation,
    ...rest,
  };
};

const unknownOutcomeBanner = (): BannerCopy =>
  banner(
    'error',
    'alert',
    __('Unexpected response from the recognition service.', 'alt-context'),
    __(
      'The probe returned a response the plugin does not recognize. Confirm the recognition service and plugin are on compatible versions.',
      'alt-context',
    ),
  );

const positiveEtaSeconds = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) && value > 0 ? Math.floor(value) : null;

const startingEtaSeconds = (result: TestConnectionResponse): number | null =>
  positiveEtaSeconds(result.warmup_eta_seconds) ?? positiveEtaSeconds(result.retry_after_seconds);

export const renderBanner = (result: TestConnectionResponse): BannerCopy => {
  if (!isTestConnectionOutcome(result.outcome)) {
    return unknownOutcomeBanner();
  }
  const outcome: TestConnectionOutcomeValue = result.outcome;
  switch (outcome) {
    case TestConnectionOutcome.CONNECTED: {
      const pairingError =
        typeof result.pairing_error === 'string' && result.pairing_error.trim() !== ''
          ? result.pairing_error.trim()
          : null;
      if (pairingError) {
        return banner(
          'warning',
          'alert',
          __('Connection successful, but tenant pairing failed.', 'alt-context'),
          pairingError,
        );
      }
      return banner(
        'success',
        'status',
        __('Connection successful.', 'alt-context'),
        __('The plugin authenticated against the recognition service and the pool is healthy.', 'alt-context'),
      );
    }
    case TestConnectionOutcome.NOT_CONFIGURED:
      return banner(
        'warning',
        'status',
        __('No recognition URL configured.', 'alt-context'),
        __('Set the API URL above before testing.', 'alt-context'),
      );
    case TestConnectionOutcome.INVALID_KEY:
      return banner(
        'error',
        'alert',
        __('API key rejected.', 'alt-context'),
        __(
          'The recognition service returned 401/403. Check the API Key field above, or ask an operator to re-issue the key.',
          'alt-context',
        ),
      );
    case TestConnectionOutcome.EXPIRED:
      return banner(
        'error',
        'alert',
        __('API key expired.', 'alt-context'),
        __('Ask an operator to rotate the key with the recognition CLI, then paste the new value here.', 'alt-context'),
      );
    case TestConnectionOutcome.REVOKED:
      return banner(
        'error',
        'alert',
        __('API key revoked.', 'alt-context'),
        __('This key has been revoked server-side. Request a fresh key and update the value above.', 'alt-context'),
      );
    case TestConnectionOutcome.TENANT_MISMATCH:
      return banner(
        'error',
        'alert',
        __('Tenant mismatch.', 'alt-context'),
        __(
          'The API key belongs to a different site. Adopt the key’s tenant to pair this site, or confirm the key was issued for this WordPress tenant.',
          'alt-context',
        ),
        { confirmPairing: true },
      );
    case TestConnectionOutcome.TENANT_PAIRING_CONFLICT:
      return banner(
        'warning',
        'alert',
        __('Tenant identity conflict.', 'alt-context'),
        __(
          'The API key is bound to a different tenant than this site. Confirm adoption before re-keying local data.',
          'alt-context',
        ),
        { confirmPairing: true },
      );
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
      return banner(
        'warning',
        'status',
        __('Recognition service is rate limiting this site.', 'alt-context'),
        wait,
      );
    }
    case TestConnectionOutcome.STARTING: {
      const eta = startingEtaSeconds(result);
      const primary =
        eta !== null
          ? sprintf(
              /* translators: %d is the remaining warmup seconds. */
              __('Description service is starting — ready in ~%d s', 'alt-context'),
              eta,
            )
          : __('Description service is starting.', 'alt-context');
      const remediation =
        eta !== null
          ? __('The description service is warming up. Suggest and describe will retry automatically.', 'alt-context')
          : __('Warming up, this can take a few minutes', 'alt-context');
      return banner('info', 'status', primary, remediation, { prefixIcon: true });
    }
    case TestConnectionOutcome.SERVER_ERROR:
      return banner(
        'error',
        'alert',
        __('Recognition service returned a server error.', 'alt-context'),
        __('Try again in a moment. If the problem persists, check the recognition service logs.', 'alt-context'),
      );
    case TestConnectionOutcome.NETWORK_ERROR:
      return banner(
        'error',
        'alert',
        __('Could not reach the recognition service.', 'alt-context'),
        __('Verify the API URL above and confirm the site can reach the recognition host.', 'alt-context'),
      );
    case TestConnectionOutcome.TLS_ERROR:
      return banner(
        'error',
        'alert',
        __('TLS handshake failed.', 'alt-context'),
        __(
          'The recognition service certificate could not be validated. Check the HTTPS endpoint and trust chain.',
          'alt-context',
        ),
      );
    default: {
      const exhaustive: never = outcome;
      return exhaustive;
    }
  }
};
