import { __ } from '@wordpress/i18n';

export const NAMING_AGREEMENT_LABEL = __('Include named people in descriptions', 'alt-context');
export const NAMING_AGREEMENT_HELP = __(
  'Names come from the People roster and are applied only when recognition is enabled.',
  'alt-context',
);

export const SOURCE_LABELS: Record<string, string> = {
  constant: __('Set via wp-config.php constant', 'alt-context'),
  option: __('Saved in database', 'alt-context'),
  filter: __('Provided by a code filter', 'alt-context'),
  default: __('Not configured', 'alt-context'),
  derived: __('Derived from the API key', 'alt-context'),
};

/**
 * R19-BR-04: single derived state for the service-URL card.
 * Rejection blanks `url` for security, so emptiness alone is not "unconfigured".
 */
export const ServiceUrlCardState = {
  CONFIGURED: 'configured',
  REJECTED: 'rejected',
  UNCONFIGURED: 'unconfigured',
} as const;

export type ServiceUrlCardStateValue =
  (typeof ServiceUrlCardState)[keyof typeof ServiceUrlCardState];

export const deriveServiceUrlCardState = (data: {
  url: string;
  url_rejection_reason: string | null;
}): ServiceUrlCardStateValue => {
  if (data.url_rejection_reason !== null) {
    return ServiceUrlCardState.REJECTED;
  }
  if (data.url.trim() !== '') {
    return ServiceUrlCardState.CONFIGURED;
  }
  return ServiceUrlCardState.UNCONFIGURED;
};

export const HealthStatus = {
  NOT_CHECKED: 'not_checked',
  REACHABLE: 'reachable',
  UNREACHABLE: 'unreachable',
} as const;

export type HealthStatusValue = (typeof HealthStatus)[keyof typeof HealthStatus];

export const HEALTH_STATUS_LABELS: Record<HealthStatusValue, string> = {
  [HealthStatus.NOT_CHECKED]: __('Not checked', 'alt-context'),
  [HealthStatus.REACHABLE]: __('Reachable', 'alt-context'),
  [HealthStatus.UNREACHABLE]: __('Unreachable', 'alt-context'),
};

export const HEALTH_STATUS_ICONS: Record<HealthStatusValue, string> = {
  [HealthStatus.NOT_CHECKED]: '\u25cb',
  [HealthStatus.REACHABLE]: '\u2713',
  [HealthStatus.UNREACHABLE]: '\u26a0',
};

export const TenantPairing = {
  PAIRED: 'paired',
  UNPAIRED: 'unpaired',
} as const;

export type TenantPairingValue = (typeof TenantPairing)[keyof typeof TenantPairing];

export const TENANT_PAIRING_ICONS: Record<TenantPairingValue, string> = {
  [TenantPairing.PAIRED]: '\u2713',
  [TenantPairing.UNPAIRED]: '\u25cb',
};

export const TENANT_PAIRING_LABELS: Record<TenantPairingValue, string> = {
  [TenantPairing.PAIRED]: __('Paired with the recognition service', 'alt-context'),
  [TenantPairing.UNPAIRED]: __('Not paired yet \u2014 check the connection to pair this tenant', 'alt-context'),
};

export const isReadOnly = (source: string): boolean => source === 'constant' || source === 'filter';
