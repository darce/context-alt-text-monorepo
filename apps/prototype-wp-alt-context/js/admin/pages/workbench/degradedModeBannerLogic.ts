import { __ } from '@wordpress/i18n';

import type { SyncHealthResponse } from '../../api/recognition/types/sync';

export const shouldShowDegradedBanner = (health: SyncHealthResponse): boolean =>
  health.breaker.state === 'open' || health.last_pull.ok === false;

export const getDegradedBannerMessage = (): string =>
  __(
    'Working offline — showing your local copy; changes will sync when the service returns.',
    'alt-context',
  );