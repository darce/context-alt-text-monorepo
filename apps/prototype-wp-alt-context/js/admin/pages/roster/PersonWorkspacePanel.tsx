import React from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';
import type { RosterEntry } from '../../api/rosterApi';
import { formatTimestamp } from '../../utils/formatTimestamp';

interface PersonWorkspacePanelProps {
  entry: RosterEntry;
}

export const PersonWorkspacePanel = ({ entry }: PersonWorkspacePanelProps): React.JSX.Element => (
  <section
    className="acx-roster__person-workspace"
    role="region"
    aria-label={sprintf(__('Person workspace: %s', 'alt-context'), entry.name)}
  >
    <header className="acx-roster__person-workspace-header">
      <h3>{entry.name}</h3>
      <p className="acx-roster__person-workspace-meta">
        {sprintf(__('%d clusters assigned', 'alt-context'), entry.cluster_count)}
      </p>
      <p className="acx-roster__person-workspace-meta">
        {sprintf(__('Projection status: %s', 'alt-context'), entry.projection_status)}
      </p>
      <p className="acx-roster__person-workspace-meta">
        {sprintf(__('Projection refreshed: %s', 'alt-context'), formatTimestamp(entry.projection_refreshed_at))}
      </p>
      <p className="acx-roster__person-workspace-meta">
        {sprintf(__('Source version: %d', 'alt-context'), entry.source_version)}
      </p>
    </header>

    <div className="acx-roster__person-workspace-summary">
      <section aria-labelledby="acx-person-workspace-clusters">
        <h4 id="acx-person-workspace-clusters">{__('Grouped cluster detail', 'alt-context')}</h4>
        <p>
          {entry.cluster_count === 0
            ? __('No curated clusters are grouped under this person yet.', 'alt-context')
            : sprintf(
                _n(
                  '%d curated cluster is currently grouped under this person.',
                  '%d curated clusters are currently grouped under this person.',
                  entry.cluster_count,
                  'alt-context',
                ),
                entry.cluster_count,
              )}
        </p>
      </section>

      <section aria-labelledby="acx-person-workspace-evidence">
        <h4 id="acx-person-workspace-evidence">{__('Person evidence', 'alt-context')}</h4>
        {entry.tags.length === 0 ? (
          <p>{__('No person tags recorded yet.', 'alt-context')}</p>
        ) : (
          <ul>
            {entry.tags.map((tag) => (
              <li key={tag}>{tag}</li>
            ))}
          </ul>
        )}
      </section>
    </div>
  </section>
);
