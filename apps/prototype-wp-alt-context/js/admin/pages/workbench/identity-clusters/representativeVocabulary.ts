/**
 * Canonical copy for missing-representative and gated-cluster states.
 * Preview surfaces and repair rows must read this module — do not hardcode.
 */
import { __, _n, sprintf } from '@wordpress/i18n';

export const REPRESENTATIVE_VOCABULARY = {
  imageUnavailable: __('Representative image unavailable', 'alt-context'),
} as const;

export function gatedClusterCopy(count: number, truncated = false): string {
  if (truncated) {
    return sprintf(
      _n(
        'At least %d group on this page missing face data',
        'At least %d groups on this page missing face data',
        count,
        'alt-context',
      ),
      count,
    );
  }
  return sprintf(
    _n('%d group missing face data', '%d groups missing face data', count, 'alt-context'),
    count,
  );
}
