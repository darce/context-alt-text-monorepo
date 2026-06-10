import { __ } from '@wordpress/i18n';

export const SOURCE_LABELS: Record<string, string> = {
  constant: __('Set via wp-config.php constant', 'alt-context'),
  option: __('Saved in database', 'alt-context'),
  filter: __('Provided by a code filter', 'alt-context'),
  default: __('Not configured', 'alt-context'),
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

export const isReadOnly = (source: string): boolean => source === 'constant' || source === 'filter';