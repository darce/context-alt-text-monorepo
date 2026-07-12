import React from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';

import type { DashboardStats } from '../../api/dashboardApi';

interface GuidanceCardProps {
  stats: DashboardStats;
}

export const GuidanceCard = ({ stats }: GuidanceCardProps): React.JSX.Element => {
  if (stats.pending_clusters_count > 0) {
    return (
      <>
        <p>
          {sprintf(
            /* translators: %d: number of pending clusters */
            __('%d faces are waiting for names.', 'alt-context'),
            stats.pending_clusters_count,
          )}
        </p>
        <a href="#/workbench?advanced=open" className="acx-link-button">
          {__('Go to Workbench', 'alt-context')}
        </a>
      </>
    );
  }

  if (stats.unassigned_persons_count > 0) {
    const reviewLabel = sprintf(
      /* translators: %d: number of unassigned persons */
      _n('Review %d unassigned person', 'Review %d unassigned persons', stats.unassigned_persons_count, 'alt-context'),
      stats.unassigned_persons_count,
    );

    return (
      <>
        <p>
          {sprintf(
            /* translators: %d: number of unassigned persons */
            _n(
              '%d person has no assigned clusters.',
              '%d persons have no assigned clusters.',
              stats.unassigned_persons_count,
              'alt-context',
            ),
            stats.unassigned_persons_count,
          )}
        </p>
        <a
          href="#/roster?tab=entries&personFilter=unassigned"
          className="acx-link-button acx-dashboard__guidance-link"
          aria-label={reviewLabel}
        >
          <span>{__('Review unassigned persons', 'alt-context')}</span>
          <span className="acx-dashboard__guidance-count">{stats.unassigned_persons_count}</span>
        </a>
      </>
    );
  }

  if (stats.people_count === 0) {
    return (
      <>
        <p>{__('Start by scanning your media library for faces.', 'alt-context')}</p>
        <a href="#/workbench?tab=scan" className="acx-link-button">
          {__('Go to Scan tab', 'alt-context')}
        </a>
      </>
    );
  }

  return <p>{__('All caught up. New faces will appear here for review.', 'alt-context')}</p>;
};
