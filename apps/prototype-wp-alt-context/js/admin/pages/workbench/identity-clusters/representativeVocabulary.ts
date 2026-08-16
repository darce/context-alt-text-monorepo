/**
 * Canonical copy for missing-representative and gated-cluster states.
 * Preview surfaces and repair rows must read this module — do not hardcode.
 */
import { _n, sprintf } from '@wordpress/i18n';

import { REPRESENTATIVE_IMAGE_UNAVAILABLE } from '../../../../components/ui/faceThumbDisplay';

export const REPRESENTATIVE_VOCABULARY = {
  imageUnavailable: REPRESENTATIVE_IMAGE_UNAVAILABLE,
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
