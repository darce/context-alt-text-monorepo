import React from 'react';
import { __ } from '@wordpress/i18n';

import type { SyncHealthResponse } from '../../api/recognition/types/sync';
import { useSyncHealth } from '../../hooks/useSyncHealth';
import { getDegradedBannerMessage, shouldShowDegradedBanner } from './degradedModeBannerLogic';

interface DegradedModeBannerViewProps {
  health: SyncHealthResponse | undefined;
}

export const DegradedModeBannerView = ({ health }: DegradedModeBannerViewProps): React.JSX.Element | null => {
  if (!health || !shouldShowDegradedBanner(health)) {
    return null;
  }

  return (
    <div
      className="acx-empty-state-warning acx-degraded-mode-banner"
      role="alert"
      aria-live="assertive"
      data-testid="acx-degraded-mode-banner"
    >
      <span className="acx-empty-state-warning__icon" aria-hidden="true" data-testid="acx-degraded-mode-banner-icon">
        !
      </span>
      <div className="acx-empty-state-warning__content">
        <p className="acx-empty-state-warning__title">{__('Working offline', 'alt-context')}</p>
        <p className="acx-empty-state-warning__message">{getDegradedBannerMessage()}</p>
      </div>
    </div>
  );
};

export const DegradedModeBanner = (): React.JSX.Element | null => {
  const { data } = useSyncHealth();

  return <DegradedModeBannerView health={data} />;
};