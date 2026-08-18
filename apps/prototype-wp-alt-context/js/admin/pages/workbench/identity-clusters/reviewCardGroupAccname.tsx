/**
 * BR-41: shared group-accname helpers for ASSIGNMENT / NAME / CLUSTER review cards.
 * MERGE keeps its own question+ordinal composition in MergeSuggestionCard (byte-identical).
 */

import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import { isValidQueueOrdinal, isValidQueueOrdinalPair } from './reviewQueueDriver';

export type ReviewCardGroupKind = 'assignment' | 'name' | 'cluster';

export { isValidQueueOrdinal, isValidQueueOrdinalPair };

/**
 * Kind-only fallback (never empty) or ordinal fold when the position/total pair is valid.
 */
export const formatReviewCardGroupLabel = (
  kind: ReviewCardGroupKind,
  queuePosition?: number,
  queueTotal?: number,
): string => {
  const hasOrdinal =
    isValidQueueOrdinalPair(queuePosition, queueTotal) && isValidQueueOrdinal(queueTotal);
  switch (kind) {
    case 'assignment':
      return hasOrdinal
        ? sprintf(
            /* translators: 1: 1-based position, 2: queue total */
            __('Face suggestion %1$d of %2$d', 'alt-context'),
            queuePosition,
            queueTotal,
          )
        : __('Face suggestion', 'alt-context');
    case 'name':
      return hasOrdinal
        ? sprintf(
            /* translators: 1: 1-based position, 2: queue total */
            __('Name suggestion %1$d of %2$d', 'alt-context'),
            queuePosition,
            queueTotal,
          )
        : __('Name suggestion', 'alt-context');
    case 'cluster':
      return hasOrdinal
        ? sprintf(
            /* translators: 1: 1-based position, 2: queue total */
            __('Face group review %1$d of %2$d', 'alt-context'),
            queuePosition,
            queueTotal,
          )
        : __('Face group review', 'alt-context');
  }
};

export type ReviewCardGroupShellProps = React.HTMLAttributes<HTMLDivElement> & {
  kind: ReviewCardGroupKind;
  labelId: string;
  queuePosition?: number;
  queueTotal?: number;
  children?: React.ReactNode;
};

/**
 * MERGE-style `role="group"` + screen-reader-text + aria-labelledby root for non-MERGE kinds.
 */
export const ReviewCardGroupShell = ({
  kind,
  labelId,
  queuePosition,
  queueTotal,
  children,
  ...rest
}: ReviewCardGroupShellProps): React.JSX.Element => {
  const label = formatReviewCardGroupLabel(kind, queuePosition, queueTotal);
  return (
    <div role="group" aria-labelledby={labelId} {...rest}>
      <span id={labelId} className="screen-reader-text">
        {label}
      </span>
      {children}
    </div>
  );
};
