import React from 'react';

import type { SyncHealthResponse } from '../../api/recognition/types/sync';
import { useSyncHealth } from '../../hooks/useSyncHealth';
import {
  getDegradedBannerMessage,
  getDegradedBannerTitle,
  getDegradedDebtLinks,
  getDegradedWarningMessage,
  isSyncOffline,
  shouldShowDegradedBanner,
} from './degradedModeBannerLogic';
import { SYNC_VOCABULARY } from './syncPresentation';

interface DegradedModeBannerViewProps {
  health: SyncHealthResponse | undefined;
}

export const DegradedModeBannerView = ({ health }: DegradedModeBannerViewProps): React.JSX.Element | null => {
  if (!health || !shouldShowDegradedBanner(health)) {
    return null;
  }

  const debtLinks = getDegradedDebtLinks(health);
  const warningMessage = getDegradedWarningMessage(health);

  const isOffline = isSyncOffline(health);

  // rg-004: alert implies assertive; advisory mode pairs status with polite instead.
  return (
    <div
      className={`acx-empty-state-warning acx-degraded-mode-banner${isOffline ? '' : ' acx-degraded-mode-banner--advisory'}`}
      role={isOffline ? 'alert' : 'status'}
      aria-live={isOffline ? 'assertive' : 'polite'}
      data-testid="acx-degraded-mode-banner"
    >
      <span className="acx-empty-state-warning__icon" aria-hidden="true" data-testid="acx-degraded-mode-banner-icon">
        !
      </span>
      <div className="acx-empty-state-warning__content">
        <p className="acx-empty-state-warning__title">{getDegradedBannerTitle(health)}</p>
        {isOffline ? <p className="acx-empty-state-warning__message">{getDegradedBannerMessage()}</p> : null}
        {warningMessage ? <p className="acx-empty-state-warning__message">{warningMessage}</p> : null}
        {debtLinks.failedOutboxHref || debtLinks.conflictsHref ? (
          <p className="acx-empty-state-warning__message">
            {debtLinks.failedOutboxHref ? (
              <a href={debtLinks.failedOutboxHref} className="acx-empty-state-warning__link">
                {SYNC_VOCABULARY.reviewFailedOps}
              </a>
            ) : null}
            {debtLinks.failedOutboxHref && debtLinks.conflictsHref ? ' · ' : null}
            {debtLinks.conflictsHref ? (
              <a href={debtLinks.conflictsHref} className="acx-empty-state-warning__link">
                {SYNC_VOCABULARY.resolveConflicts}
              </a>
            ) : null}
          </p>
        ) : null}
      </div>
    </div>
  );
};

export const DegradedModeBanner = (): React.JSX.Element | null => {
  const { data } = useSyncHealth();

  return <DegradedModeBannerView health={data} />;
};
