/**
 * Shared suggestion-query retry contract (REV2-05 / REV4-02).
 *
 * RQ v5 refetch() resolves on query error and isLoading stays false while an
 * already-errored query refetches. Callers must inspect settled isError and
 * announce in-flight via a local retrying flag.
 */

import React from 'react';
import { __ } from '@wordpress/i18n';

export const QUERY_RETRY_COPY = {
  RETRY: 'Retry',
  RETRYING_FINDINGS: 'Retrying recognition findings…',
  RETRY_FAILED_FINDINGS: 'Retry failed. Could not load recognition findings.',
  LOAD_FAILED_FINDINGS: 'Could not load recognition findings.',
  RETRYING_SUGGESTIONS: 'Retrying suggestions…',
  RETRY_FAILED_SUGGESTIONS: 'Retry failed. Could not load suggestions.',
  LOAD_FAILED_SUGGESTIONS: 'Failed to load suggestions.',
} as const;

export type SettledRefetchResult = { isError?: unknown } | null | undefined;

/** True when Promise.all(refetch) is missing or any settled result isError. */
export const settledRefetchFailed = (results: unknown): boolean =>
  !Array.isArray(results) || results.some((result) => Boolean((result as SettledRefetchResult)?.isError));

interface QueryRetryButtonProps {
  describedBy: string;
  retrying: boolean;
  retryingLabel: string;
  statusId: string;
  statusClassName: string;
  onClick: () => void;
  className: string;
}

/** Shared Retry control so every caller gets aria-busy + in-flight status. */
export const QueryRetryButton = ({
  describedBy,
  retrying,
  retryingLabel,
  statusId,
  statusClassName,
  onClick,
  className,
}: QueryRetryButtonProps): React.JSX.Element => (
  <>
    {retrying && (
      <p id={statusId} className={statusClassName} role="status" aria-live="polite">
        {retryingLabel}
      </p>
    )}
    <button
      type="button"
      className={className}
      onClick={onClick}
      aria-describedby={describedBy}
      aria-busy={retrying || undefined}
    >
      {__(QUERY_RETRY_COPY.RETRY, 'alt-context')}
    </button>
  </>
);
