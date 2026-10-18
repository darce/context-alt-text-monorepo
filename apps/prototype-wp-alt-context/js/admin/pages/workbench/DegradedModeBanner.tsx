import React from 'react';
import { __ } from '@wordpress/i18n';

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
  isLoading?: boolean;
  onRetry?: () => void;
}

export const DegradedModeBannerView = ({
  health,
  isLoading = false,
  onRetry,
}: DegradedModeBannerViewProps): React.JSX.Element => {
  const isUnknown = !isLoading && health === undefined;
  const isDegraded = health !== undefined && shouldShowDegradedBanner(health);
  const isOffline = health !== undefined && isSyncOffline(health);
  const isAdvisory = isDegraded && !isOffline;

  const unknownContent = isUnknown ? (
    <>
      <span
        className="acx-empty-state-warning__icon"
        aria-hidden="true"
        data-testid="acx-degraded-mode-banner-icon"
      >
        !
      </span>
      <div className="acx-empty-state-warning__content">
        <p className="acx-empty-state-warning__title">
          {__('Backend health unknown', 'alt-context')}
        </p>
        <p className="acx-empty-state-warning__message">
          {__('Remote analysis and description are paused until service health can be confirmed.', 'alt-context')}
        </p>
        {onRetry ? (
          <button type="button" className="button" onClick={onRetry}>
            {__('Retry health check', 'alt-context')}
          </button>
        ) : null}
      </div>
    </>
  ) : null;

  const healthContent = health && isDegraded ? (() => {
    const debtLinks = getDegradedDebtLinks(health);
    const warningMessage = getDegradedWarningMessage(health);

    return (
      <>
        <span
          className="acx-empty-state-warning__icon"
          aria-hidden="true"
          data-testid="acx-degraded-mode-banner-icon"
        >
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
      </>
    );
  })() : null;

  const politeContent = isAdvisory ? healthContent : null;
  const assertiveContent = isUnknown ? unknownContent : isOffline ? healthContent : null;

  // Both regions mount empty on the first render and retain identity. Their
  // visible banner content is swapped in only after a settled transition.
  return (
    <>
      <div
        className={politeContent
          ? 'acx-empty-state-warning acx-degraded-mode-banner acx-degraded-mode-banner--advisory'
          : 'screen-reader-text'}
        role="status"
        aria-live="polite"
        data-testid={politeContent ? 'acx-degraded-mode-banner' : undefined}
      >
        {politeContent}
      </div>
      <div
        className={assertiveContent
          ? 'acx-empty-state-warning acx-degraded-mode-banner'
          : 'screen-reader-text'}
        role="alert"
        aria-live="assertive"
        data-testid={assertiveContent ? 'acx-degraded-mode-banner' : undefined}
      >
        {assertiveContent}
      </div>
    </>
  );
};

export const DegradedModeBanner = (): React.JSX.Element => {
  const { data, isLoading, refetch } = useSyncHealth();

  return <DegradedModeBannerView health={data} isLoading={isLoading} onRetry={() => void refetch()} />;
};
