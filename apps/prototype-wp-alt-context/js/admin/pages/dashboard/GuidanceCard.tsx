import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

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
            stats.pending_clusters_count
          )}
        </p>
        <a href="#/workbench?tab=confirm" className="acx-link-button">
          {__('Go to Workbench', 'alt-context')}
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

  if (stats.unassigned_persons_count > 0) {
    return (
      <>
        <p>
          {sprintf(
            /* translators: %d: number of unassigned persons */
            __('%d persons have no assigned clusters.', 'alt-context'),
            stats.unassigned_persons_count
          )}
        </p>
        <a href="#/roster?tab=entries&personFilter=unassigned" className="acx-link-button">
          {__('Review unassigned persons', 'alt-context')}
        </a>
      </>
    );
  }

  return <p>{__('All caught up. New faces will appear here for review.', 'alt-context')}</p>;
};
