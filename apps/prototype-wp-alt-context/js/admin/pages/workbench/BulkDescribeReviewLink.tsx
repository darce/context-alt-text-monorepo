import React from 'react';
import { __ } from '@wordpress/i18n';

import { toDescriptionHistoryRun } from '../../navigation/appLinks';

interface BulkDescribeReviewLinkProps {
  runId: string | null;
  isTerminal: boolean;
  /** Reserved for a future applied-count badge; kept out of the label for now. */
  appliedCount: number;
}

/**
 * INT-01d: once a bulk describe run reaches a terminal state, link the operator
 * from the workbench to the run-scoped apply surface on the Description History
 * page (`?run=<id>`), where drafts are reviewed and written back. A plain hash
 * anchor — HashRouter resolves it without needing router context here.
 */
export const BulkDescribeReviewLink = ({
  runId,
  isTerminal,
}: BulkDescribeReviewLinkProps): React.JSX.Element | null => {
  if (runId === null || !isTerminal) {
    return null;
  }

  return (
    <a
      className="acx-media-selection__bulk-describe-review button button-secondary"
      href={toDescriptionHistoryRun(runId)}
    >
      {__('Review & apply drafts', 'alt-context')}
    </a>
  );
};
